from decimal import Decimal

from apps.employees.models import Employees
from apps.leave.models import DepartmentWorkload, VacationRequest, VacationScheduleItem

from .constants import ACTIVE_REQUEST_STATUSES
from .dates import get_vacation_day_cost, quantize_leave_days
from .ledger import get_employee_requestable_leave, get_employee_reserved_paid_days, get_employee_used_paid_days
from .querysets import exclude_converted_paid_requests

def _risk_level_for_score(risk_score):
    if risk_score >= 70:
        return VacationRequest.RISK_HIGH
    if risk_score >= 40:
        return VacationRequest.RISK_MEDIUM
    return VacationRequest.RISK_LOW

def _get_department_staffing_rule(department):
    if department is None:
        return None

    try:
        return department.staffing_rule
    except department.__class__.staffing_rule.RelatedObjectDoesNotExist:
        return None

def calculate_vacation_request_risk(
    employee,
    start_date,
    end_date,
    vacation_type,
    exclude_request_id=None,
    exclude_schedule_item_id=None,
):
    requested_cost = Decimal(get_vacation_day_cost(vacation_type, start_date, end_date))
    requestable_days = get_employee_requestable_leave(employee, start_date)
    used_days = Decimal(get_employee_used_paid_days(employee, start_date))
    reserved_days = Decimal(
        get_employee_reserved_paid_days(
            employee,
            start_date,
            exclude_request_id=exclude_request_id,
            exclude_schedule_item_id=exclude_schedule_item_id,
        )
    )
    balance_after_request = quantize_leave_days(
        requestable_days
        + Decimal(employee.manual_leave_adjustment_days)
        - used_days
        - reserved_days
        - requested_cost
    )

    department = employee.department
    staffing_rule = _get_department_staffing_rule(department)
    workload = None
    if department is not None:
        workload = DepartmentWorkload.objects.filter(
            department=department,
            year=start_date.year,
            month=start_date.month,
        ).first()

    department_load_level = workload.load_level if workload else 1
    min_staff_required = (
        workload.min_staff_required
        if workload
        else (staffing_rule.min_staff_required if staffing_rule else 0)
    )

    if department is None:
        return {
            "risk_score": 25,
            "risk_level": VacationRequest.RISK_LOW,
            "department_load_level": department_load_level,
            "overlapping_absences_count": 0,
            "remaining_staff_count": 0,
            "min_staff_required": min_staff_required,
            "balance_after_request": balance_after_request,
        }

    department_employee_ids = set(
        Employees.objects.filter(
            department=department,
            is_active_employee=True,
            date_joined__lte=end_date,
        )
        .exclude(role__in=Employees.SERVICE_ROLES)
        .values_list("id", flat=True)
    )

    overlapping_requests = VacationRequest.objects.filter(
        employee_id__in=department_employee_ids,
        status__in=ACTIVE_REQUEST_STATUSES,
        start_date__lte=end_date,
        end_date__gte=start_date,
    )
    if exclude_request_id is not None:
        overlapping_requests = overlapping_requests.exclude(pk=exclude_request_id)
    overlapping_requests = exclude_converted_paid_requests(
        overlapping_requests,
        employee_ids=department_employee_ids,
        start_date=start_date,
        end_date=end_date,
    )
    request_employee_ids = set(overlapping_requests.values_list("employee_id", flat=True))
    schedule_employee_ids = set(
        VacationScheduleItem.objects.filter(
            employee_id__in=department_employee_ids,
            status__in=VacationScheduleItem.ACTIVE_STATUSES,
            start_date__lte=end_date,
            end_date__gte=start_date,
        )
        .exclude(pk=exclude_schedule_item_id)
        .values_list("employee_id", flat=True)
    )
    overlapping_employee_ids = (request_employee_ids | schedule_employee_ids) - {employee.id}
    overlapping_absences_count = len(overlapping_employee_ids)
    remaining_staff_count = max(len(department_employee_ids) - overlapping_absences_count - 1, 0)

    max_absent = workload.max_absent if workload else (staffing_rule.max_absent if staffing_rule else 1)
    criticality_level = staffing_rule.criticality_level if staffing_rule else 3
    role_boost = 16 if employee.role == Employees.ROLE_DEPARTMENT_HEAD else 0
    paid_exception_boost = 12 if vacation_type == "paid" else 0
    staffing_boost = 0
    if min_staff_required and remaining_staff_count < min_staff_required:
        staffing_boost += 28
    if max_absent and overlapping_absences_count + 1 > max_absent:
        staffing_boost += 22
    balance_boost = 18 if vacation_type == "paid" and balance_after_request < 0 else 0

    risk_score = min(
        95,
        8
        + department_load_level * 9
        + overlapping_absences_count * 6
        + criticality_level * 3
        + role_boost
        + paid_exception_boost
        + staffing_boost
        + balance_boost,
    )

    return {
        "risk_score": risk_score,
        "risk_level": _risk_level_for_score(risk_score),
        "department_load_level": department_load_level,
        "overlapping_absences_count": overlapping_absences_count,
        "remaining_staff_count": remaining_staff_count,
        "min_staff_required": min_staff_required,
        "balance_after_request": balance_after_request,
    }

def calculate_schedule_change_risk(schedule_item, new_start_date, new_end_date):
    risk_payload = calculate_vacation_request_risk(
        schedule_item.employee,
        new_start_date,
        new_end_date,
        schedule_item.vacation_type,
        exclude_schedule_item_id=schedule_item.id,
    )
    return {
        "risk_score": risk_payload["risk_score"],
        "risk_level": risk_payload["risk_level"],
        "department_load_level": risk_payload["department_load_level"],
        "overlapping_absences_count": risk_payload["overlapping_absences_count"],
        "remaining_staff_count": risk_payload["remaining_staff_count"],
        "min_staff_required": risk_payload["min_staff_required"],
        "balance_after_change": risk_payload["balance_after_request"],
    }
