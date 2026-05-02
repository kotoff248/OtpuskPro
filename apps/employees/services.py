from django.db import transaction

from apps.accounts.services import get_accessible_departments, get_current_employee
from apps.employees.models import Departments, EmployeePosition, ProductionGroup


def update_context_with_departments(request, context):
    current_employee = get_current_employee(request)
    departments = get_accessible_departments(current_employee)

    if request.method == "POST" and "department" in request.POST:
        request.session["selected_department"] = request.POST.get("department", "all")

    selected_department = request.session.get("selected_department", "all")
    available_ids = {str(department.id) for department in departments}
    if selected_department != "all" and selected_department not in available_ids:
        selected_department = "all"
        request.session["selected_department"] = "all"

    context.update(
        {
            "departments": departments,
            "employee_positions": EmployeePosition.objects.select_related(
                "department",
                "production_group",
            ).filter(
                department__in=departments,
                is_active=True,
            ).order_by("department__name", "production_group__name", "title"),
            "selected_department": selected_department,
        }
    )
    return context


def _normalize_filter_value(value):
    value = str(value or "all").strip()
    return value if value else "all"


def resolve_production_group_filter_context(current_employee, selected_department="all", selected_group="all"):
    selected_department = _normalize_filter_value(selected_department)
    selected_group = _normalize_filter_value(selected_group)

    accessible_departments = list(get_accessible_departments(current_employee))
    accessible_department_ids = {department.id for department in accessible_departments}

    selected_department_id = None
    if selected_department != "all":
        try:
            candidate_department_id = int(selected_department)
        except (TypeError, ValueError):
            selected_department = "all"
        else:
            if candidate_department_id in accessible_department_ids:
                selected_department_id = candidate_department_id
                selected_department = str(candidate_department_id)
            else:
                selected_department = "all"

    group_options = list(
        ProductionGroup.objects.select_related("department")
        .filter(department_id__in=accessible_department_ids)
        .order_by("department__name", "name")
    )
    for group in group_options:
        group.is_available_for_selected_department = (
            selected_department_id is None or group.department_id == selected_department_id
        )
    allowed_group_ids = {
        group.id
        for group in group_options
        if group.is_available_for_selected_department
    }

    selected_group_id = None
    if selected_group != "all":
        try:
            candidate_group_id = int(selected_group)
        except (TypeError, ValueError):
            selected_group = "all"
        else:
            if candidate_group_id in allowed_group_ids:
                selected_group_id = candidate_group_id
                selected_group = str(candidate_group_id)
            else:
                selected_group = "all"

    return {
        "group_options": group_options,
        "selected_group": selected_group,
        "selected_group_id": selected_group_id,
        "selected_department": selected_department,
        "selected_department_id": selected_department_id,
        "show_group_department_labels": len(accessible_department_ids) > 1,
    }


@transaction.atomic
def archive_employee(employee):
    if employee.user_id and employee.user is not None:
        employee.user.is_active = False
        employee.user.save(update_fields=["is_active"])

    Departments.objects.filter(head=employee).update(head=None)
    Departments.objects.filter(deputy=employee).update(deputy=None)
    employee.is_active_employee = False
    employee.save(update_fields=["is_active_employee"])
