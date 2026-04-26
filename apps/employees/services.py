from django.db import transaction

from apps.accounts.services import get_accessible_departments, get_current_employee
from apps.employees.models import Departments


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
            "selected_department": selected_department,
        }
    )
    return context


@transaction.atomic
def archive_employee(employee):
    if employee.user_id and employee.user is not None:
        employee.user.is_active = False
        employee.user.save(update_fields=["is_active"])

    Departments.objects.filter(head=employee).update(head=None)
    employee.is_active_employee = False
    employee.save(update_fields=["is_active_employee"])
