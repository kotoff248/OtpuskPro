import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError

from apps.employees.models import DepartmentCoverageRule, Employees, ProductionGroupSubstitutionRule
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


def _load_risk_boost(load_level):
    return {
        1: 0,
        2: 4,
        3: 8,
        4: 14,
        5: 20,
    }.get(load_level, 8)


def _overlap_risk_boost(overlapping_absences_count):
    if overlapping_absences_count <= 0:
        return 0
    if overlapping_absences_count <= 3:
        return overlapping_absences_count * 5
    return min(24, 15 + (overlapping_absences_count - 3) * 3)


def _criticality_risk_boost(criticality_level, *, step=4):
    return max(0, criticality_level - 3) * step


def _get_department_staffing_rule(department):
    if department is None:
        return None

    try:
        return department.staffing_rule
    except department.__class__.staffing_rule.RelatedObjectDoesNotExist:
        return None


def _iter_month_day_weights(start_date, end_date):
    cursor = date(start_date.year, start_date.month, 1)
    final_month = date(end_date.year, end_date.month, 1)
    while cursor <= final_month:
        month_last_day = date(cursor.year, cursor.month, calendar.monthrange(cursor.year, cursor.month)[1])
        segment_start = max(start_date, cursor)
        segment_end = min(end_date, month_last_day)
        if segment_start <= segment_end:
            yield cursor.year, cursor.month, (segment_end - segment_start).days + 1

        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)


def _round_weighted_metric(total, day_count, *, minimum=0, maximum=None):
    if day_count <= 0:
        return minimum

    value = int((Decimal(total) / Decimal(day_count)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    value = max(value, minimum)
    if maximum is not None:
        value = min(value, maximum)
    return value


def _get_weighted_department_workload(department, start_date, end_date, staffing_rule):
    month_weights = list(_iter_month_day_weights(start_date, end_date))
    if not month_weights:
        return {
            "department_load_level": 1,
            "min_staff_required": staffing_rule.min_staff_required if staffing_rule else 0,
            "max_absent": staffing_rule.max_absent if staffing_rule else 1,
        }

    workloads = {
        (workload.year, workload.month): workload
        for workload in DepartmentWorkload.objects.filter(
            department=department,
            year__in={year for year, _, _ in month_weights},
            month__in={month for _, month, _ in month_weights},
        )
    }
    fallback_min_staff = staffing_rule.min_staff_required if staffing_rule else 0
    fallback_max_absent = staffing_rule.max_absent if staffing_rule else 1
    total_days = sum(days for _, _, days in month_weights)
    load_total = 0
    min_staff_total = 0
    max_absent_total = 0

    for year, month, days in month_weights:
        workload = workloads.get((year, month))
        load_total += (workload.load_level if workload else 1) * days
        min_staff_total += (workload.min_staff_required if workload else fallback_min_staff) * days
        max_absent_total += (workload.max_absent if workload else fallback_max_absent) * days

    return {
        "department_load_level": _round_weighted_metric(load_total, total_days, minimum=1, maximum=5),
        "min_staff_required": _round_weighted_metric(min_staff_total, total_days, minimum=0),
        "max_absent": _round_weighted_metric(max_absent_total, total_days, minimum=1),
    }


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
    if vacation_type == "paid":
        try:
            used_days = Decimal(get_employee_used_paid_days(employee, start_date))
            reserved_days = Decimal(
                get_employee_reserved_paid_days(
                    employee,
                    start_date,
                    exclude_request_id=exclude_request_id,
                    exclude_schedule_item_id=exclude_schedule_item_id,
                )
            )
        except ValidationError:
            used_days = Decimal("0")
            reserved_days = requestable_days + Decimal(employee.manual_leave_adjustment_days)
    else:
        used_days = Decimal("0")
        reserved_days = Decimal("0")
    balance_after_request = quantize_leave_days(
        requestable_days
        + Decimal(employee.manual_leave_adjustment_days)
        - used_days
        - reserved_days
        - requested_cost
    )

    department = employee.department
    staffing_rule = _get_department_staffing_rule(department)
    if department is not None:
        weighted_workload = _get_weighted_department_workload(department, start_date, end_date, staffing_rule)
    else:
        weighted_workload = {
            "department_load_level": 1,
            "min_staff_required": staffing_rule.min_staff_required if staffing_rule else 0,
            "max_absent": staffing_rule.max_absent if staffing_rule else 1,
        }
    department_load_level = weighted_workload["department_load_level"]
    min_staff_required = weighted_workload["min_staff_required"]

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
    department_staff_count = len(department_employee_ids)
    max_absent = weighted_workload["max_absent"]
    if department_staff_count:
        min_staff_required = min(min_staff_required, department_staff_count)
        max_absent = min(max_absent, department_staff_count)
    else:
        min_staff_required = 0
        max_absent = 0

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
    remaining_staff_count = max(department_staff_count - overlapping_absences_count - 1, 0)

    group_staffing_boost = 0
    employee_group = (
        employee.employee_position.production_group
        if getattr(employee, "employee_position_id", None) and employee.employee_position
        else None
    )
    if employee_group is not None:
        group_staff_members = list(
            Employees.objects.select_related(
                "employee_position",
                "employee_position__production_group",
            ).filter(
                department=department,
                is_active_employee=True,
                date_joined__lte=end_date,
                employee_position__production_group=employee_group,
            ).exclude(role__in=Employees.SERVICE_ROLES)
        )
        group_staff_ids = {staff_member.id for staff_member in group_staff_members}
        coverage_rule = DepartmentCoverageRule.objects.filter(
            department=department,
            production_group=employee_group,
        ).first()
        absent_with_current_request = set(overlapping_employee_ids) | {employee.id}
        absent_group_count = len(group_staff_ids & absent_with_current_request)
        present_primary_count = len(group_staff_ids - absent_with_current_request)
        covered_by_substitution = 0
        shortage = 0
        if coverage_rule is not None:
            shortage = max(coverage_rule.min_staff_required - present_primary_count, 0)
            if shortage:
                substitution_rules = ProductionGroupSubstitutionRule.objects.filter(
                    department=department,
                    source_group=employee_group,
                )
                for substitution_rule in substitution_rules:
                    substitute_staff_ids = set(
                        Employees.objects.filter(
                            department=department,
                            is_active_employee=True,
                            date_joined__lte=end_date,
                            employee_position__production_group_id=substitution_rule.substitute_group_id,
                        ).exclude(role__in=Employees.SERVICE_ROLES).values_list("id", flat=True)
                    )
                    substitute_coverage_rule = DepartmentCoverageRule.objects.filter(
                        department=department,
                        production_group_id=substitution_rule.substitute_group_id,
                    ).first()
                    substitute_minimum = substitute_coverage_rule.min_staff_required if substitute_coverage_rule is not None else 0
                    present_substitute_count = len(substitute_staff_ids - absent_with_current_request)
                    free_substitute_capacity = max(present_substitute_count - substitute_minimum, 0)
                    covered_now = min(
                        shortage - covered_by_substitution,
                        free_substitute_capacity,
                        substitution_rule.max_covered_absences,
                    )
                    if covered_now <= 0:
                        continue
                    covered_by_substitution += covered_now
                    if covered_by_substitution >= shortage:
                        break
            effective_present_count = present_primary_count + covered_by_substitution
            if coverage_rule.min_staff_required and effective_present_count < coverage_rule.min_staff_required:
                group_staffing_boost += 56
            elif (
                coverage_rule.min_staff_required
                and shortage
                and covered_by_substitution
                and present_primary_count < coverage_rule.min_staff_required <= effective_present_count
            ):
                group_staffing_boost += 30
            if absent_group_count > coverage_rule.max_absent:
                group_staffing_boost += 44
            elif coverage_rule.max_absent and absent_group_count == coverage_rule.max_absent:
                group_staffing_boost += 8
            if absent_group_count:
                group_staffing_boost += _criticality_risk_boost(coverage_rule.criticality_level, step=3)

    leadership_boost = 0
    department_deputy_id = getattr(department, "deputy_id", None)
    department_head_id = getattr(department, "head_id", None)
    if employee.role == Employees.ROLE_DEPARTMENT_HEAD and department_deputy_id in overlapping_employee_ids:
        leadership_boost += 24
    if employee.id == department_deputy_id and department_head_id in overlapping_employee_ids:
        leadership_boost += 24

    criticality_level = staffing_rule.criticality_level if staffing_rule else 3
    role_boost = 10 if employee.role == Employees.ROLE_DEPARTMENT_HEAD else 0
    staffing_boost = 0
    absent_with_current_request = overlapping_absences_count + 1
    if min_staff_required and remaining_staff_count < min_staff_required:
        staffing_boost += 52
    elif min_staff_required and remaining_staff_count == min_staff_required:
        staffing_boost += 12
    if max_absent and absent_with_current_request > max_absent:
        staffing_boost += 44
    elif max_absent and absent_with_current_request == max_absent:
        staffing_boost += 10
    elif max_absent and max_absent >= 3 and absent_with_current_request == max_absent - 1:
        staffing_boost += 5
    balance_boost = 18 if vacation_type == "paid" and balance_after_request < 0 else 0

    risk_score = min(
        95,
        10
        + _load_risk_boost(department_load_level)
        + _overlap_risk_boost(overlapping_absences_count)
        + _criticality_risk_boost(criticality_level)
        + role_boost
        + leadership_boost
        + staffing_boost
        + group_staffing_boost
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
