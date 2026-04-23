from apps.accounts.services import (
    get_current_employee,
    get_managed_department_id,
    is_department_head_employee,
    is_enterprise_head_employee,
    is_hr_employee,
    is_management_employee,
)
from apps.leave.models import VacationRequest


def pending_requests_count(request):
    current_employee = get_current_employee(request)
    if current_employee is None or not is_management_employee(current_employee):
        return {"pending_requests_count": 0}

    queryset = VacationRequest.objects.filter(status=VacationRequest.STATUS_PENDING)

    if is_department_head_employee(current_employee):
        managed_department_id = get_managed_department_id(current_employee)
        if not managed_department_id:
            return {"pending_requests_count": 0}
        queryset = queryset.filter(employee__department_id=managed_department_id)
    elif is_hr_employee(current_employee) or is_enterprise_head_employee(current_employee):
        pass

    return {"pending_requests_count": queryset.count()}
