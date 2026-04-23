from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.formats import date_format
from django.utils.http import url_has_allowed_host_and_scheme

from apps.accounts.services import (
    employee_required,
    get_current_employee,
    get_user_context,
    is_manager_user,
    manager_required,
)
from apps.employees.models import Departments, Employees
from apps.leave.services import get_employee_remaining_balance, get_employee_vacation_requests

from .forms import EmployeeCreateForm, EmployeeUpdateForm
from .services import update_context_with_departments


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
        "employee_vacation_days": "vacation_days",
        "employee_department": "department",
        "employee_is_manager": "is_manager",
    }
    for old_name, new_name in field_map.items():
        if old_name in data and new_name not in data:
            data[new_name] = data.get(old_name)
    return data


@employee_required
def main(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    employee = get_current_employee(request)
    is_manager = is_manager_user(request.user)
    all_requests = get_employee_vacation_requests(employee)
    total_balance = get_employee_remaining_balance(employee)

    context.update(
        {
            "employee": employee,
            "all_requests": all_requests,
            "total_balance": total_balance,
            "is_manager": is_manager,
            "can_edit_employee": is_manager,
            "show_manager_fields": is_manager,
        }
    )
    return render(request, "main.html", context)


@employee_required
def employee_profile(request, employee_id):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    current_employee = get_current_employee(request)
    current_employee_id = current_employee.id if current_employee else None
    is_manager = is_manager_user(request.user)

    if not is_manager and current_employee_id != employee_id:
        messages.error(request, "У вас нет прав для просмотра чужого профиля.")
        return redirect("main")

    employee = get_object_or_404(Employees.objects.select_related("department"), id=employee_id)
    all_requests = get_employee_vacation_requests(employee)
    total_balance = get_employee_remaining_balance(employee)

    context.update(
        {
            "employee": employee,
            "all_requests": all_requests,
            "total_balance": total_balance,
            "can_edit_employee": is_manager,
            "show_manager_fields": is_manager,
        }
    )
    return render(request, "employee_profile.html", context)


@employee_required
@manager_required
def update_employee(request, employee_id):
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
    is_manager = is_manager_user(request.user)

    if request.method == "POST" and not is_manager:
        messages.error(request, "У вас нет прав для добавления сотрудников.")
        return redirect("employees")

    if request.method == "POST" and is_manager and ("last_name" in request.POST or "employee_last_name" in request.POST):
        form = EmployeeCreateForm(_normalize_employee_form_data(request.POST))
        if form.is_valid():
            form.save()
            messages.success(request, "Сотрудник создан.")
        else:
            messages.error(request, _form_errors_to_messages(form) or "Не удалось создать сотрудника.")
        return redirect("employees")

    employees_qs = Employees.objects.select_related("department").order_by("last_name", "first_name", "middle_name")
    department_id = "all"
    if is_manager:
        department_id = request.GET.get("department", request.session.get("selected_department", "all"))
        if department_id and department_id != "all":
            employees_qs = employees_qs.filter(department_id=department_id)
    elif current_employee and current_employee.department_id:
        employees_qs = employees_qs.filter(department=current_employee.department)

    status = request.GET.get("status", "None")
    if status == "True":
        employees_qs = employees_qs.filter(is_working=True)
    elif status == "False":
        employees_qs = employees_qs.filter(is_working=False)

    employees_list = []
    for employee in employees_qs:
        employees_list.append(
            {
                "id": employee.id,
                "name": employee.full_name,
                "position": employee.position,
                "date_joined": date_format(employee.date_joined, "j E Y", use_l10n=True),
                "vacation_days": get_employee_remaining_balance(employee),
                "is_working": employee.is_working,
            }
        )

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"employees": employees_list})

    context.update(
        {
            "employees": employees_list,
            "employees_count": len(employees_list),
            "selected_status": status,
            "selected_department": department_id
            if is_manager
            else current_employee.department.id if current_employee and current_employee.department_id else "all",
            "is_manager": is_manager,
            "show_manager_fields": is_manager,
        }
    )
    return render(request, "employees.html", context)


@employee_required
@manager_required
def departments(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    departments_qs = Departments.objects.all()

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
