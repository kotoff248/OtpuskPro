from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.formats import date_format
from django.utils.http import url_has_allowed_host_and_scheme

from apps.accounts.services import (
    can_access_departments_page,
    can_edit_employee_data,
    can_view_employee,
    employee_required,
    get_current_employee,
    get_managed_department_id,
    get_user_context,
    is_department_head_employee,
    is_enterprise_head_employee,
    is_hr_employee,
)
from apps.employees.models import Departments, Employees
from apps.leave.services import (
    get_employee_leave_summary,
    get_employee_leave_summaries,
    get_employee_vacation_requests,
)

from .forms import EmployeeCreateForm, EmployeeUpdateForm
from .services import update_context_with_departments


def _form_errors_to_messages(form):
    errors = []
    for field_errors in form.errors.values():
        errors.extend(field_errors)
    return " ".join(str(error) for error in errors)


def _format_days(value):
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _serialize_employee_row(employee, leave_summary):
    return {
        "id": employee.id,
        "name": employee.full_name,
        "position": employee.position,
        "date_joined": date_format(employee.date_joined, "j E Y", use_l10n=True),
        "available_days": _format_days(leave_summary["available"]),
        "is_working": employee.is_working,
    }


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


def _get_visible_employees_queryset(current_employee):
    queryset = Employees.objects.select_related("department", "managed_department").order_by(
        "last_name",
        "first_name",
        "middle_name",
    )
    if current_employee is None:
        return queryset.none()
    if is_hr_employee(current_employee) or is_enterprise_head_employee(current_employee):
        return queryset
    if is_department_head_employee(current_employee):
        managed_department_id = get_managed_department_id(current_employee)
        return queryset.filter(department_id=managed_department_id) if managed_department_id else queryset.none()
    if current_employee.department_id:
        return queryset.filter(department_id=current_employee.department_id)
    return queryset.filter(pk=current_employee.pk)


@employee_required
def main(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    employee = get_current_employee(request)
    all_requests = get_employee_vacation_requests(employee)
    leave_summary = get_employee_leave_summary(employee)

    context.update(
        {
            "employee": employee,
            "all_requests": all_requests,
            "leave_summary": leave_summary,
            "total_balance": leave_summary["available"],
            "can_edit_employee": can_edit_employee_data(employee),
            "show_manager_fields": can_edit_employee_data(employee),
        }
    )
    return render(request, "main.html", context)


@employee_required
def employee_profile(request, employee_id):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    current_employee = get_current_employee(request)
    employee = get_object_or_404(Employees.objects.select_related("department", "managed_department"), id=employee_id)

    if not can_view_employee(current_employee, employee):
        messages.error(request, "У вас нет прав для просмотра этого профиля.")
        return redirect("main")

    all_requests = get_employee_vacation_requests(employee)
    leave_summary = get_employee_leave_summary(employee)

    context.update(
        {
            "employee": employee,
            "all_requests": all_requests,
            "leave_summary": leave_summary,
            "total_balance": leave_summary["available"],
            "can_edit_employee": can_edit_employee_data(current_employee),
            "show_manager_fields": can_edit_employee_data(current_employee),
        }
    )
    return render(request, "employee_profile.html", context)


@employee_required
def update_employee(request, employee_id):
    current_employee = get_current_employee(request)
    if not can_edit_employee_data(current_employee):
        messages.error(request, "Только HR может редактировать карточки сотрудников.")
        return redirect("main")

    employee = get_object_or_404(Employees, id=employee_id)

    if request.method != "POST":
        return redirect("employee_profile", employee_id=employee_id)

    next_path = request.POST.get("next_path")
    if next_path and url_has_allowed_host_and_scheme(
        next_path,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        redirect_response = redirect(next_path)
    else:
        redirect_response = redirect("employee_profile", employee_id=employee_id)

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
def employees(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    current_employee = get_current_employee(request)
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

    employees_qs = _get_visible_employees_queryset(current_employee)
    department_id = "all"
    if is_hr_employee(current_employee) or is_enterprise_head_employee(current_employee):
        department_id = request.GET.get("department", request.session.get("selected_department", "all"))
        if department_id and department_id != "all":
            employees_qs = employees_qs.filter(department_id=department_id)
    elif is_department_head_employee(current_employee):
        managed_department_id = get_managed_department_id(current_employee)
        employees_qs = employees_qs.filter(department_id=managed_department_id) if managed_department_id else employees_qs.none()
        department_id = str(managed_department_id) if managed_department_id else "all"
    elif current_employee and current_employee.department_id:
        employees_qs = employees_qs.filter(department_id=current_employee.department_id)
        department_id = str(current_employee.department_id)

    status = request.GET.get("status", "None")
    if status == "True":
        employees_qs = employees_qs.filter(is_working=True)
    elif status == "False":
        employees_qs = employees_qs.filter(is_working=False)

    employees_qs = list(employees_qs)
    leave_summaries = get_employee_leave_summaries(employees_qs)
    employees_list = [
        _serialize_employee_row(employee, leave_summaries[employee.id])
        for employee in employees_qs
    ]

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"employees": employees_list})

    context.update(
        {
            "employees": employees_list,
            "employees_count": len(employees_list),
            "selected_status": status,
            "selected_department": department_id,
            "can_manage_employees": can_edit,
            "show_manager_fields": can_edit,
        }
    )
    return render(request, "employees.html", context)


@employee_required
def departments(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    current_employee = get_current_employee(request)

    if not can_access_departments_page(current_employee):
        messages.error(request, "У вас нет прав для доступа к разделу отделов.")
        return redirect("main")

    departments_qs = Departments.objects.select_related("head").order_by("name")
    if is_department_head_employee(current_employee):
        managed_department_id = get_managed_department_id(current_employee)
        departments_qs = departments_qs.filter(id=managed_department_id) if managed_department_id else departments_qs.none()

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        departments_data = list(departments_qs.values("id", "name", "date_added"))
        return JsonResponse({"departments": departments_data})

    context.update(
        {
            "departments": departments_qs,
            "departments_count": departments_qs.count(),
        }
    )
    return render(request, "departments.html", context)
