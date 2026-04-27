from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.leave.models import (
    VacationEntitlementAllocation,
    VacationEntitlementPeriod,
    VacationRequest,
    VacationScheduleItem,
)

from .constants import (
    ACTIVE_REQUEST_STATUSES,
    BALANCE_AFFECTING_TYPES,
    LEAVE_ADVANCE_MONTHS,
    SCHEDULE_BALANCE_STATUSES,
)
from .dates import (
    add_months_safe,
    add_years_safe,
    format_ru_date,
    get_chargeable_leave_days,
    get_employee_joined_date,
    normalize_date_value,
    quantize_leave_days,
)
from .querysets import exclude_converted_paid_requests

def get_working_year_bounds(employee, as_of_date=None):
    as_of_date = normalize_date_value(as_of_date or timezone.localdate())
    start_date = get_employee_joined_date(employee)
    if as_of_date < start_date:
        working_year_start = start_date
    else:
        completed_years = as_of_date.year - start_date.year
        anniversary_this_year = add_years_safe(start_date, completed_years)
        if anniversary_this_year > as_of_date:
            completed_years -= 1
        working_year_start = add_years_safe(start_date, max(completed_years, 0))
    working_year_end = add_years_safe(working_year_start, 1) - timedelta(days=1)
    return working_year_start, working_year_end

def _calculate_accrued_leave_without_ledger(employee, as_of_date):
    as_of_date = normalize_date_value(as_of_date)
    date_joined = get_employee_joined_date(employee)
    if as_of_date < date_joined:
        return Decimal("0.00")

    annual_leave = Decimal(employee.annual_paid_leave_days)
    working_year_start, working_year_end = get_working_year_bounds(employee, as_of_date)
    completed_years = max(0, working_year_start.year - date_joined.year)
    while add_years_safe(date_joined, completed_years) > working_year_start:
        completed_years -= 1

    fully_accrued = annual_leave * completed_years
    elapsed_days = (min(as_of_date, working_year_end) - working_year_start).days + 1
    working_year_days = (working_year_end - working_year_start).days + 1
    current_year_accrued = annual_leave * Decimal(elapsed_days) / Decimal(working_year_days)
    return quantize_leave_days(fully_accrued + current_year_accrued)

def _calculate_requestable_leave_without_ledger(employee, as_of_date):
    as_of_date = normalize_date_value(as_of_date)
    date_joined = get_employee_joined_date(employee)
    if as_of_date < date_joined:
        return Decimal("0.00")

    annual_leave = Decimal(employee.annual_paid_leave_days)
    working_year_start, _ = get_working_year_bounds(employee, as_of_date)
    completed_years = max(0, working_year_start.year - date_joined.year)
    while add_years_safe(date_joined, completed_years) > working_year_start:
        completed_years -= 1

    fully_requestable = annual_leave * completed_years
    current_year_accrued = _calculate_accrued_leave_without_ledger(employee, as_of_date) - quantize_leave_days(
        annual_leave * completed_years
    )
    if completed_years == 0:
        first_year_advance_available_from = add_months_safe(date_joined, LEAVE_ADVANCE_MONTHS)
        current_year_requestable = annual_leave if as_of_date >= first_year_advance_available_from else current_year_accrued
    else:
        current_year_requestable = annual_leave
    return quantize_leave_days(fully_requestable + current_year_requestable)

def iter_employee_working_years(employee, through_date=None):
    through_date = through_date or timezone.localdate()
    date_joined = get_employee_joined_date(employee)
    if through_date < date_joined:
        return

    cursor = date_joined
    working_year_number = 1
    while cursor <= through_date:
        period_end = add_years_safe(cursor, 1) - timedelta(days=1)
        yield working_year_number, cursor, period_end
        cursor = period_end + timedelta(days=1)
        working_year_number += 1

def _entitlement_available_from(period_start, working_year_number):
    return add_months_safe(period_start, LEAVE_ADVANCE_MONTHS) if working_year_number == 1 else period_start

def _entitlement_must_use_by(period_end):
    return add_years_safe(period_end, 1)

def sync_employee_entitlement_periods(employee, through_date=None):
    through_date = normalize_date_value(through_date or timezone.localdate())
    if employee is None:
        return []
    date_joined = get_employee_joined_date(employee)
    if through_date < date_joined:
        return []

    period_ids = []
    for working_year_number, period_start, period_end in iter_employee_working_years(employee, through_date):
        defaults = {
            "period_start": period_start,
            "period_end": period_end,
            "entitled_days": quantize_leave_days(employee.annual_paid_leave_days),
            "available_from": _entitlement_available_from(period_start, working_year_number),
            "must_use_by": _entitlement_must_use_by(period_end),
        }
        period, _ = VacationEntitlementPeriod.objects.update_or_create(
            employee=employee,
            working_year_number=working_year_number,
            defaults=defaults,
        )
        period_ids.append(period.id)

    return list(
        VacationEntitlementPeriod.objects.filter(id__in=period_ids)
        .order_by("period_start")
    )

def _period_accrued_days(period, as_of_date):
    if as_of_date < period.period_start:
        return Decimal("0.00")
    if as_of_date >= period.period_end:
        return quantize_leave_days(period.entitled_days)

    elapsed_days = (as_of_date - period.period_start).days + 1
    working_year_days = (period.period_end - period.period_start).days + 1
    return quantize_leave_days(Decimal(period.entitled_days) * Decimal(elapsed_days) / Decimal(working_year_days))

def _period_requestable_days(period, as_of_date):
    if as_of_date < period.period_start:
        return Decimal("0.00")
    if period.working_year_number == 1 and as_of_date < period.available_from:
        return _period_accrued_days(period, as_of_date)
    return quantize_leave_days(period.entitled_days)

def _collect_paid_ledger_sources(employee):
    sources = []
    requests = VacationRequest.objects.filter(
        employee=employee,
        vacation_type__in=BALANCE_AFFECTING_TYPES,
        status__in=ACTIVE_REQUEST_STATUSES,
    )
    requests = exclude_converted_paid_requests(requests, employee_ids=[employee.id])
    for request_obj in requests:
        start_date = normalize_date_value(request_obj.start_date)
        end_date = normalize_date_value(request_obj.end_date)
        sources.append(
            {
                "kind": VacationEntitlementAllocation.SOURCE_REQUEST,
                "id": request_obj.id,
                "start_date": start_date,
                "end_date": end_date,
                "days": quantize_leave_days(
                    get_chargeable_leave_days(start_date, end_date, request_obj.vacation_type)
                ),
                "state": (
                    VacationEntitlementAllocation.STATE_USED
                    if request_obj.status == VacationRequest.STATUS_APPROVED
                    else VacationEntitlementAllocation.STATE_RESERVED
                ),
                "request": request_obj,
                "schedule_item": None,
            }
        )

    schedule_items = VacationScheduleItem.objects.filter(
        employee=employee,
        vacation_type__in=BALANCE_AFFECTING_TYPES,
        status__in=SCHEDULE_BALANCE_STATUSES,
    )
    for item in schedule_items:
        start_date = normalize_date_value(item.start_date)
        end_date = normalize_date_value(item.end_date)
        chargeable_days = item.chargeable_days or get_chargeable_leave_days(start_date, end_date, item.vacation_type)
        sources.append(
            {
                "kind": VacationEntitlementAllocation.SOURCE_SCHEDULE,
                "id": item.id,
                "start_date": start_date,
                "end_date": end_date,
                "days": quantize_leave_days(chargeable_days),
                "state": (
                    VacationEntitlementAllocation.STATE_USED
                    if item.status == VacationScheduleItem.STATUS_APPROVED
                    else VacationEntitlementAllocation.STATE_RESERVED
                ),
                "request": None,
                "schedule_item": item,
            }
        )

    sources.sort(key=lambda source: (source["start_date"], source["end_date"], source["kind"], source["id"]))
    return sources

def _source_state_for_date(source, as_of_date):
    if source["state"] != VacationEntitlementAllocation.STATE_USED:
        return VacationEntitlementAllocation.STATE_RESERVED
    return (
        VacationEntitlementAllocation.STATE_USED
        if source["start_date"] <= as_of_date
        else VacationEntitlementAllocation.STATE_RESERVED
    )

def rebuild_employee_leave_ledger(employee, as_of_date=None, strict=True):
    if employee is None:
        return []

    as_of_date = normalize_date_value(as_of_date or timezone.localdate())
    sources = _collect_paid_ledger_sources(employee)
    source_horizon = max([as_of_date, *[source["end_date"] for source in sources]], default=as_of_date)
    periods = sync_employee_entitlement_periods(employee, source_horizon)

    VacationEntitlementAllocation.objects.filter(employee=employee).delete()
    allocated_by_period = {period.id: Decimal("0.00") for period in periods}
    allocations = []

    for source in sources:
        days_left = quantize_leave_days(source["days"])
        if days_left <= 0:
            continue

        for period in periods:
            requestable_on_start = _period_requestable_days(period, source["start_date"])
            period_left = quantize_leave_days(requestable_on_start - allocated_by_period[period.id])
            if period_left <= 0:
                continue

            allocated_days = min(days_left, period_left)
            if allocated_days <= 0:
                continue

            allocations.append(
                VacationEntitlementAllocation(
                    employee=employee,
                    entitlement_period=period,
                    vacation_request=source["request"],
                    schedule_item=source["schedule_item"],
                    source_kind=source["kind"],
                    state=_source_state_for_date(source, as_of_date),
                    allocated_days=allocated_days,
                )
            )
            allocated_by_period[period.id] = quantize_leave_days(allocated_by_period[period.id] + allocated_days)
            days_left = quantize_leave_days(days_left - allocated_days)
            if days_left <= 0:
                break

        if days_left > 0 and strict:
            raise ValidationError(
                "Недостаточно отпускных прав по рабочим годам для оплачиваемого отпуска."
            )

    if allocations:
        VacationEntitlementAllocation.objects.bulk_create(allocations)

    return periods

def _ensure_employee_leave_ledger(employee, as_of_date=None):
    as_of_date = normalize_date_value(as_of_date or timezone.localdate())
    sources = _collect_paid_ledger_sources(employee)
    source_horizon = max([as_of_date, *[source["end_date"] for source in sources]], default=as_of_date)
    has_allocations = VacationEntitlementAllocation.objects.filter(employee=employee).exists()

    if as_of_date != timezone.localdate() or (sources and not has_allocations):
        return rebuild_employee_leave_ledger(employee, as_of_date=as_of_date)

    return sync_employee_entitlement_periods(employee, source_horizon)

def _ledger_totals(employee, as_of_date=None, exclude_request_id=None, exclude_schedule_item_id=None):
    as_of_date = normalize_date_value(as_of_date or timezone.localdate())
    periods = _ensure_employee_leave_ledger(employee, as_of_date=as_of_date)
    period_ids = [period.id for period in periods]
    allocations = VacationEntitlementAllocation.objects.filter(
        employee=employee,
        entitlement_period_id__in=period_ids,
    )
    if exclude_request_id is not None:
        allocations = allocations.exclude(vacation_request_id=exclude_request_id)
    if exclude_schedule_item_id is not None:
        allocations = allocations.exclude(schedule_item_id=exclude_schedule_item_id)

    allocations_by_period = {
        period.id: {
            VacationEntitlementAllocation.STATE_USED: Decimal("0.00"),
            VacationEntitlementAllocation.STATE_RESERVED: Decimal("0.00"),
        }
        for period in periods
    }
    for allocation in allocations:
        allocations_by_period[allocation.entitlement_period_id][allocation.state] += Decimal(allocation.allocated_days)

    accrued = Decimal("0.00")
    requestable = Decimal("0.00")
    used = Decimal("0.00")
    reserved = Decimal("0.00")
    for period in periods:
        period_requestable = _period_requestable_days(period, as_of_date)
        accrued += _period_accrued_days(period, as_of_date)
        requestable += period_requestable
        if period_requestable <= 0:
            continue
        used += allocations_by_period[period.id][VacationEntitlementAllocation.STATE_USED]
        reserved += allocations_by_period[period.id][VacationEntitlementAllocation.STATE_RESERVED]

    manual_adjustment = quantize_leave_days(employee.manual_leave_adjustment_days)
    accrued = quantize_leave_days(accrued)
    requestable = quantize_leave_days(requestable)
    used = quantize_leave_days(used)
    reserved = quantize_leave_days(reserved)
    accrued_balance = quantize_leave_days(accrued + manual_adjustment - used - reserved)
    available = quantize_leave_days(max(requestable + manual_adjustment - used - reserved, Decimal("0")))
    advance_available = quantize_leave_days(max(available - max(accrued_balance, Decimal("0")), Decimal("0")))

    return {
        "annual_entitlement": quantize_leave_days(employee.annual_paid_leave_days),
        "accrued": accrued,
        "requestable": requestable,
        "reserved": reserved,
        "used": used,
        "accrued_balance": accrued_balance,
        "advance_available": advance_available,
        "available": available,
        "manual_adjustment": manual_adjustment,
    }

def get_employee_used_paid_days(employee, as_of_date=None):
    return _ledger_totals(employee, as_of_date=as_of_date)["used"]

def get_employee_reserved_paid_days(employee, as_of_date=None, exclude_request_id=None, exclude_schedule_item_id=None):
    return _ledger_totals(
        employee,
        as_of_date=as_of_date,
        exclude_request_id=exclude_request_id,
        exclude_schedule_item_id=exclude_schedule_item_id,
    )["reserved"]

def get_employee_accrued_leave(employee, as_of_date=None):
    as_of_date = normalize_date_value(as_of_date or timezone.localdate())
    if as_of_date < get_employee_joined_date(employee):
        return Decimal("0.00")
    periods = sync_employee_entitlement_periods(employee, as_of_date)
    return quantize_leave_days(sum((_period_accrued_days(period, as_of_date) for period in periods), Decimal("0.00")))

def get_employee_requestable_leave(employee, as_of_date=None):
    as_of_date = normalize_date_value(as_of_date or timezone.localdate())
    if as_of_date < get_employee_joined_date(employee):
        return Decimal("0.00")
    periods = sync_employee_entitlement_periods(employee, as_of_date)
    return quantize_leave_days(sum((_period_requestable_days(period, as_of_date) for period in periods), Decimal("0.00")))

def get_employee_available_balance(employee, as_of_date=None, exclude_request_id=None, exclude_schedule_item_id=None):
    return _ledger_totals(
        employee,
        as_of_date=as_of_date,
        exclude_request_id=exclude_request_id,
        exclude_schedule_item_id=exclude_schedule_item_id,
    )["available"]

def get_employee_leave_summary(employee, as_of_date=None):
    return _ledger_totals(employee, as_of_date=as_of_date)

def get_employee_leave_summaries(employees, as_of_date=None):
    as_of_date = normalize_date_value(as_of_date or timezone.localdate())
    employees = list(employees)
    if not employees:
        return {}
    return get_employee_list_leave_summaries(employees, as_of_date)

def get_employee_list_leave_summaries(employees, as_of_date=None):
    as_of_date = normalize_date_value(as_of_date or timezone.localdate())
    employees = list(employees)
    if not employees:
        return {}

    employee_ids = [employee.id for employee in employees]
    request_sources = VacationRequest.objects.filter(
        employee_id__in=employee_ids,
        vacation_type__in=BALANCE_AFFECTING_TYPES,
        status__in=ACTIVE_REQUEST_STATUSES,
    )
    request_sources = exclude_converted_paid_requests(request_sources, employee_ids=employee_ids)
    employees_with_sources = set(
        request_sources.values_list("employee_id", flat=True)
    )
    employees_with_sources.update(
        VacationScheduleItem.objects.filter(
            employee_id__in=employee_ids,
            vacation_type__in=BALANCE_AFFECTING_TYPES,
            status__in=SCHEDULE_BALANCE_STATUSES,
        ).values_list("employee_id", flat=True)
    )
    employees_with_allocations = set(
        VacationEntitlementAllocation.objects.filter(employee_id__in=employee_ids).values_list("employee_id", flat=True)
    )
    employee_by_id = {employee.id: employee for employee in employees}
    for employee_id in employees_with_sources - employees_with_allocations:
        rebuild_employee_leave_ledger(employee_by_id[employee_id], as_of_date=as_of_date)

    periods = list(
        VacationEntitlementPeriod.objects.filter(
            employee_id__in=employee_ids,
            period_start__lte=as_of_date,
        ).order_by("employee_id", "period_start")
    )
    periods_by_employee = {employee.id: [] for employee in employees}
    for period in periods:
        periods_by_employee[period.employee_id].append(period)

    used_by_period = {period.id: Decimal("0.00") for period in periods}
    reserved_by_period = {period.id: Decimal("0.00") for period in periods}
    for allocation in VacationEntitlementAllocation.objects.filter(
        employee_id__in=employee_ids,
        entitlement_period_id__in=used_by_period.keys(),
    ).values("entitlement_period_id", "state", "allocated_days"):
        if allocation["state"] == VacationEntitlementAllocation.STATE_USED:
            used_by_period[allocation["entitlement_period_id"]] += Decimal(allocation["allocated_days"])
        else:
            reserved_by_period[allocation["entitlement_period_id"]] += Decimal(allocation["allocated_days"])

    summaries = {}
    for employee in employees:
        annual_entitlement = quantize_leave_days(employee.annual_paid_leave_days)
        employee_periods = periods_by_employee[employee.id]
        if employee_periods:
            accrued = quantize_leave_days(
                sum((_period_accrued_days(period, as_of_date) for period in employee_periods), Decimal("0.00"))
            )
            requestable = quantize_leave_days(
                sum((_period_requestable_days(period, as_of_date) for period in employee_periods), Decimal("0.00"))
            )
            used = Decimal("0.00")
            reserved = Decimal("0.00")
            for period in employee_periods:
                if _period_requestable_days(period, as_of_date) <= 0:
                    continue
                used += used_by_period[period.id]
                reserved += reserved_by_period[period.id]
            used = quantize_leave_days(used)
            reserved = quantize_leave_days(reserved)
        else:
            accrued = _calculate_accrued_leave_without_ledger(employee, as_of_date)
            requestable = _calculate_requestable_leave_without_ledger(employee, as_of_date)
            used = Decimal("0.00")
            reserved = Decimal("0.00")
        manual_adjustment = quantize_leave_days(employee.manual_leave_adjustment_days)
        accrued_balance = quantize_leave_days(accrued + manual_adjustment - used - reserved)
        available = quantize_leave_days(max(requestable + manual_adjustment - used - reserved, Decimal("0")))
        advance_available = quantize_leave_days(max(available - max(accrued_balance, Decimal("0")), Decimal("0")))
        summaries[employee.id] = {
            "annual_entitlement": annual_entitlement,
            "accrued": accrued,
            "requestable": requestable,
            "used": used,
            "reserved": reserved,
            "accrued_balance": accrued_balance,
            "advance_available": advance_available,
            "available": available,
            "manual_adjustment": manual_adjustment,
        }

    return summaries

def _entitlement_status_for_row(period, remaining_days, as_of_date):
    if as_of_date < period.period_start:
        return "future", "Будущий"
    if remaining_days <= 0:
        return "closed", "Закрыт"
    if period.must_use_by < as_of_date:
        return "overdue", "Просрочен"
    if period.period_start <= as_of_date <= period.period_end:
        return "current", "Текущий"
    if period.must_use_by <= as_of_date + timedelta(days=90):
        return "attention", "Скоро срок"
    return "remaining", "Остаток"

def get_employee_entitlement_rows(employee, as_of_date=None, limit=6):
    as_of_date = as_of_date or timezone.localdate()
    periods = _ensure_employee_leave_ledger(employee, as_of_date=as_of_date)
    allocations = VacationEntitlementAllocation.objects.filter(
        employee=employee,
        entitlement_period_id__in=[period.id for period in periods],
    ).values("entitlement_period_id", "state", "allocated_days")

    totals_by_period = {
        period.id: {
            VacationEntitlementAllocation.STATE_USED: Decimal("0.00"),
            VacationEntitlementAllocation.STATE_RESERVED: Decimal("0.00"),
        }
        for period in periods
    }
    for allocation in allocations:
        totals_by_period[allocation["entitlement_period_id"]][allocation["state"]] += Decimal(allocation["allocated_days"])

    rows = []
    for period in periods:
        used_days = quantize_leave_days(totals_by_period[period.id][VacationEntitlementAllocation.STATE_USED])
        reserved_days = quantize_leave_days(totals_by_period[period.id][VacationEntitlementAllocation.STATE_RESERVED])
        remaining_days = quantize_leave_days(max(Decimal(period.entitled_days) - used_days - reserved_days, Decimal("0")))
        status_key, status_label = _entitlement_status_for_row(period, remaining_days, as_of_date)
        rows.append(
            {
                "id": period.id,
                "working_year_number": period.working_year_number,
                "period_label": f"{format_ru_date(period.period_start)} - {format_ru_date(period.period_end)}",
                "period_start": period.period_start,
                "period_end": period.period_end,
                "entitled_days": quantize_leave_days(period.entitled_days),
                "used_days": used_days,
                "reserved_days": reserved_days,
                "remaining_days": remaining_days,
                "available_now_days": quantize_leave_days(
                    max(_period_requestable_days(period, as_of_date) - used_days - reserved_days, Decimal("0"))
                ),
                "available_from": period.available_from,
                "must_use_by": period.must_use_by,
                "status_key": status_key,
                "status_label": status_label,
            }
        )

    problem_rows = [row for row in rows if row["status_key"] in {"overdue", "attention"} and row["remaining_days"] > 0]
    recent_rows = rows[-limit:]
    selected = {row["id"]: row for row in [*problem_rows, *recent_rows]}
    return sorted(selected.values(), key=lambda row: row["period_start"], reverse=True)

def get_employee_remaining_balance(employee):
    return get_employee_available_balance(employee)
