from datetime import date
from decimal import Decimal

from apps.employees.models import Employees
from apps.leave.models import VacationEntitlementPeriod, VacationScheduleItem
from apps.leave.services.dates import add_months_safe, get_chargeable_leave_days, quantize_leave_days
from apps.leave.services.ledger import get_employee_entitlement_rows, rebuild_employee_leave_ledger


URGENT_CLOSURE_DEMO_TARGET_COUNT = 2
URGENT_CLOSURE_DEMO_CANDIDATE_POOL_SIZE = URGENT_CLOSURE_DEMO_TARGET_COUNT
URGENT_CLOSURE_DEMO_DEADLINE_DAYS = (3, 4)
URGENT_CLOSURE_DEMO_DEADLINE_DAY_LIMIT = max(URGENT_CLOSURE_DEMO_DEADLINE_DAYS)
URGENT_CLOSURE_DEMO_TARGET_REMAINING_DAYS = Decimal("3.00")
FULL_YEAR_MIN_PAID_DAYS = Decimal("28.00")
PARTIAL_YEAR_MIN_PAID_DAYS = Decimal("14.00")


def demo_urgent_closure_join_date(schedule_end_year, employee_index):
    if employee_index > URGENT_CLOSURE_DEMO_CANDIDATE_POOL_SIZE:
        return None
    return date(schedule_end_year - 1, 1, 3 + employee_index)


def demo_urgent_closure_join_dates(planning_year):
    schedule_end_year = planning_year - 1
    return {
        demo_urgent_closure_join_date(schedule_end_year, index)
        for index in range(1, URGENT_CLOSURE_DEMO_CANDIDATE_POOL_SIZE + 1)
    } - {None}


def is_demo_urgent_closure_employee(employee, planning_year):
    return getattr(employee, "date_joined", None) in demo_urgent_closure_join_dates(planning_year)


def _candidate_employees_for_demo_cases(planning_year, employees=None):
    demo_join_dates = demo_urgent_closure_join_dates(planning_year)

    if employees is None:
        employees = Employees.objects.filter(
            role=Employees.ROLE_EMPLOYEE,
            is_active_employee=True,
        )
    else:
        employees = [
            employee
            for employee in employees
            if employee.role == Employees.ROLE_EMPLOYEE
            and employee.is_active_employee
            and not employee.is_service_account
        ]

    demo_candidates = []
    fallback_candidates = []
    for employee in employees:
        if employee.date_joined in demo_join_dates:
            demo_candidates.append(employee)
        else:
            fallback_candidates.append(employee)

    selected_ids = set()
    ordered_candidates = []
    for employee in sorted(demo_candidates, key=lambda item: (item.date_joined, item.login, item.id)):
        selected_ids.add(employee.id)
        ordered_candidates.append(employee)
    for employee in sorted(fallback_candidates, key=lambda item: (item.date_joined, item.login, item.id)):
        if employee.id in selected_ids:
            continue
        selected_ids.add(employee.id)
        ordered_candidates.append(employee)
    return ordered_candidates


def _demo_deadline(planning_year, case_index):
    day_index = min(max(case_index, 1), len(URGENT_CLOSURE_DEMO_DEADLINE_DAYS)) - 1
    day = URGENT_CLOSURE_DEMO_DEADLINE_DAYS[day_index]
    return date(planning_year, 1, day)


def _get_or_prepare_urgent_period(employee, planning_year, case_index):
    target_deadline = _demo_deadline(planning_year, case_index)
    deadline_start = date(planning_year, 1, 1)
    deadline_end = date(planning_year, 1, URGENT_CLOSURE_DEMO_DEADLINE_DAY_LIMIT)
    urgent_period = (
        VacationEntitlementPeriod.objects.filter(
            employee=employee,
            must_use_by__gte=deadline_start,
            must_use_by__lte=deadline_end,
        )
        .order_by("must_use_by", "period_start")
        .first()
    )

    if urgent_period is None:
        urgent_period = (
            VacationEntitlementPeriod.objects.filter(
                employee=employee,
                period_end__lt=deadline_start,
                available_from__lte=target_deadline,
                must_use_by__lte=date(planning_year, 12, 31),
            )
            .order_by("must_use_by", "period_start")
            .first()
        )
    if urgent_period is None:
        return None

    if urgent_period.must_use_by != target_deadline:
        urgent_period.must_use_by = target_deadline
        urgent_period.save(update_fields=["must_use_by", "updated_at"])
    return urgent_period


def _visible_remaining_days(employee, planning_end, working_year_number):
    rows = get_employee_entitlement_rows(employee, as_of_date=planning_end, limit=100)
    row = next(
        (
            entitlement_row
            for entitlement_row in rows
            if entitlement_row["working_year_number"] == working_year_number
        ),
        None,
    )
    if row is None:
        return Decimal("0.00"), Decimal("0.00")
    used_or_reserved = quantize_leave_days(row["used_days"] + row["reserved_days"])
    return row["remaining_days"], used_or_reserved


def _schedule_item_end_for_chargeable_days(item, target_days):
    target_days = int(target_days)
    if target_days <= 0:
        return None

    cursor = item.start_date
    while cursor <= item.end_date:
        chargeable_days = get_chargeable_leave_days(item.start_date, cursor, item.vacation_type)
        if chargeable_days == target_days:
            return cursor
        if chargeable_days > target_days:
            break
        cursor = date.fromordinal(cursor.toordinal() + 1)
    return None


def _shorten_schedule_item(item, reduce_days):
    reduce_days = int(reduce_days)
    if reduce_days <= 0:
        return False

    target_days = int(item.chargeable_days) - reduce_days
    if target_days <= 0:
        item.status = VacationScheduleItem.STATUS_CANCELLED
        item.manager_comment = "Исторический демо-остаток: часть отпуска не была использована до срока."
        item.save(update_fields=["status", "manager_comment"])
        return True

    new_end_date = _schedule_item_end_for_chargeable_days(item, target_days)
    if new_end_date is None or new_end_date >= item.end_date:
        return False

    item.end_date = new_end_date
    item.chargeable_days = target_days
    item.manager_comment = "Исторический демо-остаток: отпуск использован не полностью."
    item.save(update_fields=["end_date", "chargeable_days", "manager_comment"])
    return True


def _schedule_item_usable_days_for_period(item, urgent_period):
    if item.end_date <= urgent_period.must_use_by:
        return quantize_leave_days(item.chargeable_days)
    usable_end = min(item.end_date, urgent_period.must_use_by)
    if usable_end < item.start_date:
        return Decimal("0.00")
    return quantize_leave_days(get_chargeable_leave_days(item.start_date, usable_end, item.vacation_type))


def _historical_schedule_item_candidates(employee, urgent_period, planning_year):
    items = (
        VacationScheduleItem.objects.select_related("schedule")
        .filter(
            employee=employee,
            vacation_type="paid",
            status__in=VacationScheduleItem.BALANCE_STATUSES,
            schedule__year__lt=planning_year,
            start_date__lte=urgent_period.must_use_by,
        )
        .order_by("start_date", "id")
    )
    candidates = []
    for item in items:
        usable_days = _schedule_item_usable_days_for_period(item, urgent_period)
        if usable_days <= 0:
            continue
        if item.chargeable_days > 14:
            reduction_priority = 0
        elif item.chargeable_days < 14:
            reduction_priority = 1
        else:
            reduction_priority = 2
        candidates.append(
            (
                reduction_priority,
                -int(item.chargeable_days),
                item.start_date,
                item.id,
                item,
                usable_days,
            )
        )
    return [(candidate[-2], candidate[-1]) for candidate in sorted(candidates)]


def _historical_usable_schedule_days(employee, urgent_period, planning_year):
    return quantize_leave_days(
        sum(
            (
                usable_days
                for _, usable_days in _historical_schedule_item_candidates(employee, urgent_period, planning_year)
            ),
            Decimal("0.00"),
        )
    )


def _calendar_year_min_paid_days(employee, year):
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    eligibility_start = max(year_start, add_months_safe(employee.date_joined, 6))
    if eligibility_start > year_end:
        return Decimal("0.00")
    if eligibility_start <= year_start:
        return FULL_YEAR_MIN_PAID_DAYS
    if eligibility_start <= date(year, 9, 30):
        return PARTIAL_YEAR_MIN_PAID_DAYS
    return Decimal("0.00")


def _calendar_year_paid_schedule_days(employee, year):
    return quantize_leave_days(
        sum(
            (
                item.chargeable_days
                for item in VacationScheduleItem.objects.filter(
                    employee=employee,
                    schedule__year=year,
                    vacation_type="paid",
                    status__in=VacationScheduleItem.BALANCE_STATUSES,
                )
            ),
            Decimal("0.00"),
        )
    )


def _calendar_year_reducible_days(employee, year):
    return max(
        _calendar_year_paid_schedule_days(employee, year) - _calendar_year_min_paid_days(employee, year),
        Decimal("0.00"),
    )


def _shape_historical_usage_for_urgent_period(employee, urgent_period, planning_year, planning_end):
    target_remaining_days = URGENT_CLOSURE_DEMO_TARGET_REMAINING_DAYS
    target_used_days = quantize_leave_days(Decimal(urgent_period.entitled_days) - target_remaining_days)
    if target_used_days <= 0:
        return False

    for _attempt in range(8):
        visible_remaining, used_or_reserved_days = _visible_remaining_days(
            employee,
            planning_end,
            urgent_period.working_year_number,
        )
        if visible_remaining == target_remaining_days:
            return True
        if visible_remaining > target_remaining_days:
            return False

        usable_schedule_days = _historical_usable_schedule_days(employee, urgent_period, planning_year)
        excess_days = quantize_leave_days(usable_schedule_days - target_used_days)
        if excess_days <= 0:
            return False

        for item, usable_days in _historical_schedule_item_candidates(employee, urgent_period, planning_year):
            reduce_days = min(excess_days, usable_days)
            reduce_days = min(reduce_days, _calendar_year_reducible_days(employee, item.schedule.year))
            if item.chargeable_days > 14:
                reduce_days = min(reduce_days, Decimal(item.chargeable_days - 14))
            if reduce_days <= 0:
                continue
            if _shorten_schedule_item(item, reduce_days):
                rebuild_employee_leave_ledger(employee, strict=False)
                urgent_period.refresh_from_db()
                break
        else:
            return False

    visible_remaining, _ = _visible_remaining_days(employee, planning_end, urgent_period.working_year_number)
    return visible_remaining == target_remaining_days


def ensure_demo_urgent_closure_cases(*, planning_year, employees=None):
    planning_end = date(planning_year, 12, 31)
    stats = {
        "urgent_closures": 0,
        "days": 0,
        "employee_review": 0,
    }

    for employee in _candidate_employees_for_demo_cases(planning_year, employees=employees):
        if stats["urgent_closures"] >= URGENT_CLOSURE_DEMO_TARGET_COUNT:
            break

        rebuild_employee_leave_ledger(employee, strict=False)
        urgent_period = _get_or_prepare_urgent_period(employee, planning_year, stats["urgent_closures"] + 1)
        if urgent_period is None:
            continue

        if not _shape_historical_usage_for_urgent_period(employee, urgent_period, planning_year, planning_end):
            continue

        visible_remaining, _ = _visible_remaining_days(employee, planning_end, urgent_period.working_year_number)
        stats["urgent_closures"] += 1
        stats["days"] += int(visible_remaining)

    return stats
