from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from apps.accounts.services import (
    can_access_departments_page,
    can_delete_employee,
    can_edit_employee_data,
    can_view_employee,
    employee_required,
    get_current_employee,
    get_user_context,
    is_authorized_person_employee,
    is_hr_employee,
)
from apps.employees.models import Employees

from .forms import DepartmentCreateForm, EmployeeCreateForm, EmployeeUpdateForm
from .page_contexts import (
    build_departments_page_context,
    build_departments_queryset,
    build_employee_profile_context,
    build_employees_page_context,
    build_main_profile_context,
    serialize_departments_queryset,
)
from .services import archive_employee, update_context_with_departments


def _form_errors_to_messages(form):
    errors = []
    for field_errors in form.errors.values():
        errors.extend(field_errors)
    return " ".join(str(error) for error in errors)


def _normalize_employee_form_data(post_data):
    data = post_data.copy()
    field_map = {
        "employee_last_name": "last_name",
        "employee_first_name": "first_name",
        "employee_middle_name": "middle_name",
        "employee_position": "position",
        "employee_date_joined": "date_joined",
        "employee_vacation_days": "annual_paid_leave_days",
        "employee_annual_paid_leave_days": "annual_paid_leave_days",
        "vacation_days": "annual_paid_leave_days",
        "employee_department": "department",
        "employee_role": "role",
    }
    for old_name, new_name in field_map.items():
        if old_name in data and new_name not in data:
            data[new_name] = data.get(old_name)
    return data


def _get_employee_redirect_response(request, employee_id):
    next_path = request.POST.get("next_path")
    if next_path and url_has_allowed_host_and_scheme(
        next_path,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_path)
    return redirect("employee_profile", employee_id=employee_id)


@employee_required
def main(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    employee = get_current_employee(request)
    if is_authorized_person_employee(employee):
        return redirect("applications")

    context.update(build_main_profile_context(employee))
    return render(request, "main.html", context)


@employee_required
def employee_profile(request, employee_id):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    current_employee = get_current_employee(request)
    if is_authorized_person_employee(current_employee):
        return redirect("applications")
    employee = get_object_or_404(
        Employees.objects.select_related("department", "managed_department").exclude(role__in=Employees.SERVICE_ROLES),
        id=employee_id,
    )

    if not can_view_employee(current_employee, employee):
        messages.error(request, "У вас нет прав для просмотра этого профиля.")
        return redirect("main")

    context.update(build_employee_profile_context(current_employee, employee))
    return render(request, "employee_profile.html", context)


@employee_required
def update_employee(request, employee_id):
    current_employee = get_current_employee(request)
    if not can_edit_employee_data(current_employee):
        messages.error(request, "Только HR может редактировать карточки сотрудников.")
        return redirect("main")

    employee = get_object_or_404(Employees.objects.exclude(role__in=Employees.SERVICE_ROLES), id=employee_id)
    if not employee.is_active_employee:
        messages.error(request, "Архивного сотрудника нельзя редактировать.")
        return redirect("employee_profile", employee_id=employee_id)

    if request.method != "POST":
        return redirect("employee_profile", employee_id=employee_id)

    redirect_response = _get_employee_redirect_response(request, employee_id)
    form = EmployeeUpdateForm(_normalize_employee_form_data(request.POST), instance=employee)
    if not form.is_valid():
        messages.error(request, _form_errors_to_messages(form) or "Не удалось обновить данные сотрудника.")
        return redirect_response

    updated_employee = form.save()
    if form.cleaned_data.get("password") and request.user.pk == updated_employee.user_id and updated_employee.user is not None:
        update_session_auth_hash(request, updated_employee.user)

    messages.success(request, "Данные сотрудника обновлены.")
    return redirect_response


@employee_required
def delete_employee(request, employee_id):
    current_employee = get_current_employee(request)
    employee = get_object_or_404(
        Employees.objects.select_related("user").exclude(role__in=Employees.SERVICE_ROLES),
        id=employee_id,
    )

    if request.method != "POST":
        return redirect("employee_profile", employee_id=employee_id)

    if not can_delete_employee(current_employee, employee):
        messages.error(request, "У вас нет прав для удаления этого сотрудника.")
        return redirect("employee_profile", employee_id=employee_id)

    archive_employee(employee)
    messages.success(request, "Сотрудник удалён из активного состава.")
    return redirect("employees")


@employee_required
def employees(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    current_employee = get_current_employee(request)
    if is_authorized_person_employee(current_employee):
        messages.error(request, "У вас нет прав для доступа к списку сотрудников.")
        return redirect("applications")
    can_edit = can_edit_employee_data(current_employee)

    if request.method == "POST" and not can_edit:
        messages.error(request, "Только HR может добавлять сотрудников.")
        return redirect("employees")

    if request.method == "POST" and can_edit and ("last_name" in request.POST or "employee_last_name" in request.POST):
        form = EmployeeCreateForm(_normalize_employee_form_data(request.POST))
        if form.is_valid():
            form.save()
            messages.success(request, "Сотрудник создан.")
        else:
            messages.error(request, _form_errors_to_messages(form) or "Не удалось создать сотрудника.")
        return redirect("employees")

    employees_context = build_employees_page_context(current_employee, request.GET, request.session)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"employees": employees_context["employees"]})

    employees_context.update(
        {
            "can_manage_employees": can_edit,
            "show_manager_fields": can_edit,
        }
    )
    context.update(employees_context)
    return render(request, "employees.html", context)


@employee_required
def departments(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    current_employee = get_current_employee(request)
    can_create_department = is_hr_employee(current_employee)

    if not can_access_departments_page(current_employee):
        messages.error(request, "У вас нет прав для доступа к разделу отделов.")
        return redirect("main")

    department_modal_open = False
    if request.method == "POST":
        if not can_create_department:
            messages.error(request, "Только HR может создавать отделы.")
            return redirect("departments")

        department_create_form = DepartmentCreateForm(request.POST)
        if department_create_form.is_valid():
            department_create_form.save()
            messages.success(request, "Отдел создан.")
            return redirect("departments")

        department_modal_open = True
        messages.error(request, _form_errors_to_messages(department_create_form) or "Не удалось создать отдел.")
    else:
        department_create_form = DepartmentCreateForm()

    departments_qs = build_departments_queryset(current_employee)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"departments": serialize_departments_queryset(departments_qs)})

    context.update(
        build_departments_page_context(
            departments_qs,
            department_create_form,
            department_modal_open,
            can_create_department,
        )
    )
    return render(request, "departments.html", context)
