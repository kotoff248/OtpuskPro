from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from apps.accounts.services import (
    can_delete_employee,
    can_edit_employee_data,
    get_managed_department_id,
    is_department_head_employee,
    is_enterprise_head_employee,
    is_hr_employee,
)
from apps.employees.models import Departments, Employees
from apps.leave.models import VacationRequest, VacationScheduleItem
from apps.leave.services.ledger import (
    get_employee_entitlement_rows,
    get_employee_list_leave_summaries,
    get_employee_leave_summary,
)
from apps.leave.services.querysets import exclude_converted_paid_requests
from apps.leave.services.requests import get_employee_vacation_requests


def _format_days(value):
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _get_current_vacation_employee_ids(employee_ids, as_of_date=None):
    employee_ids = list(employee_ids)
    if not employee_ids:
        return set()

    today = as_of_date or timezone.localdate()
    current_requests = VacationRequest.objects.filter(
        employee_id__in=employee_ids,
        status=VacationRequest.STATUS_APPROVED,
        start_date__lte=today,
        end_date__gte=today,
    )
    current_requests = exclude_converted_paid_requests(
        current_requests,
        employee_ids=employee_ids,
        start_date=today,
        end_date=today,
    )
    request_employee_ids = current_requests.values_list("employee_id", flat=True)
    schedule_employee_ids = VacationScheduleItem.objects.filter(
        employee_id__in=employee_ids,
        status__in=VacationScheduleItem.ACTIVE_STATUSES,
        start_date__lte=today,
        end_date__gte=today,
    ).values_list("employee_id", flat=True)
    return set(request_employee_ids).union(schedule_employee_ids)


def _serialize_employee_row(employee, leave_summary, is_currently_on_vacation=None):
    if is_currently_on_vacation is None:
        is_currently_on_vacation = employee.id in _get_current_vacation_employee_ids([employee.id])
    is_working_now = not is_currently_on_vacation
    return {
        "id": employee.id,
        "name": employee.full_name,
        "position": employee.position,
        "department_name": employee.department.name if employee.department else "Не указан",
        "date_joined": date_format(employee.date_joined, "j E Y", use_l10n=True),
        "available_days": _format_days(leave_summary["available"]),
        "is_working": is_working_now,
        "status_label": "Работает" if is_working_now else "В отпуске",
        "profile_url": reverse("employee_profile", args=[employee.id]),
    }


def _get_employee_status_context(employee):
    is_currently_on_vacation = employee.id in _get_current_vacation_employee_ids([employee.id])
    is_working_now = not is_currently_on_vacation
    return {
        "employee_is_working": is_working_now,
        "employee_status_label": "Работает" if is_working_now else "В отпуске",
    }


def _get_visible_employees_queryset(current_employee):
    queryset = Employees.objects.select_related("department", "managed_department").filter(is_active_employee=True).exclude(
        role__in=Employees.SERVICE_ROLES
    ).order_by(
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


def _normalize_employee_search_query(value):
    return " ".join((value or "").split())


def _filter_employees_by_name(queryset, search_query):
    for token in search_query.split():
        queryset = queryset.filter(
            Q(last_name__icontains=token)
            | Q(first_name__icontains=token)
            | Q(middle_name__icontains=token)
        )
    return queryset


def _build_leave_profile_context(employee):
    leave_summary = get_employee_leave_summary(employee)
    context = {
        "employee": employee,
        "all_requests": get_employee_vacation_requests(employee),
        "leave_summary": leave_summary,
        "entitlement_rows": get_employee_entitlement_rows(employee),
        "total_balance": leave_summary["available"],
    }
    context.update(_get_employee_status_context(employee))
    return context


def build_main_profile_context(employee):
    can_edit = can_edit_employee_data(employee)
    context = _build_leave_profile_context(employee)
    context.update(
        {
            "can_edit_employee": can_edit,
            "show_manager_fields": can_edit,
            "sidebar_section": "profile",
        }
    )
    return context


def build_employee_profile_context(current_employee, employee):
    can_edit = can_edit_employee_data(current_employee) and employee.is_active_employee
    context = _build_leave_profile_context(employee)
    context.update(
        {
            "can_edit_employee": can_edit,
            "can_delete_employee": can_delete_employee(current_employee, employee),
            "show_manager_fields": can_edit,
            "sidebar_section": "employees" if current_employee and current_employee.id != employee.id else "profile",
        }
    )
    return context


def build_employees_page_context(current_employee, query_params, session):
    employees_qs = _get_visible_employees_queryset(current_employee)
    department_id = "all"
    if is_hr_employee(current_employee) or is_enterprise_head_employee(current_employee):
        department_id = query_params.get("department", session.get("selected_department", "all"))
        if department_id and department_id != "all":
            employees_qs = employees_qs.filter(department_id=department_id)
    elif is_department_head_employee(current_employee):
        managed_department_id = get_managed_department_id(current_employee)
        employees_qs = employees_qs.filter(department_id=managed_department_id) if managed_department_id else employees_qs.none()
        department_id = str(managed_department_id) if managed_department_id else "all"
    elif current_employee and current_employee.department_id:
        employees_qs = employees_qs.filter(department_id=current_employee.department_id)
        department_id = str(current_employee.department_id)

    status = query_params.get("status", "None")
    search_query = _normalize_employee_search_query(query_params.get("search", ""))
    if search_query:
        employees_qs = _filter_employees_by_name(employees_qs, search_query)

    employees_qs = list(employees_qs)
    current_vacation_employee_ids = _get_current_vacation_employee_ids(employee.id for employee in employees_qs)
    if status == "True":
        employees_qs = [employee for employee in employees_qs if employee.id not in current_vacation_employee_ids]
    elif status == "False":
        employees_qs = [employee for employee in employees_qs if employee.id in current_vacation_employee_ids]

    leave_summaries = get_employee_list_leave_summaries(employees_qs)
    employees_list = [
        _serialize_employee_row(
            employee,
            leave_summaries[employee.id],
            is_currently_on_vacation=employee.id in current_vacation_employee_ids,
        )
        for employee in employees_qs
    ]

    return {
        "employees": employees_list,
        "employees_count": len(employees_list),
        "selected_status": status,
        "selected_department": department_id,
        "search_query": search_query,
    }


def build_departments_queryset(current_employee):
    departments_qs = Departments.objects.select_related("head").annotate(
        employee_count=Count("employees", filter=Q(employees__is_active_employee=True))
    ).order_by("name")
    if is_department_head_employee(current_employee):
        managed_department_id = get_managed_department_id(current_employee)
        departments_qs = departments_qs.filter(id=managed_department_id) if managed_department_id else departments_qs.none()
    return departments_qs


def serialize_departments_queryset(departments_qs):
    return list(departments_qs.values("id", "name", "date_added"))


def build_departments_page_context(departments_qs, department_create_form, department_modal_open, can_create_department):
    return {
        "departments": departments_qs,
        "departments_count": departments_qs.count(),
        "can_create_department": can_create_department,
        "department_create_form": department_create_form,
        "department_head_candidates": department_create_form.fields["head"].queryset,
        "department_modal_open": department_modal_open,
    }
