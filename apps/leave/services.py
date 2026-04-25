import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache

import holidays

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.dateformat import format as date_format

from apps.employees.models import Employees
from apps.leave.models import VacationRequest, VacationScheduleItem


ACTIVE_REQUEST_STATUSES = (
    VacationRequest.STATUS_PENDING,
    VacationRequest.STATUS_APPROVED,
)
CALENDAR_VISIBLE_STATUSES = (
    VacationRequest.STATUS_PENDING,
    VacationRequest.STATUS_APPROVED,
    VacationRequest.STATUS_REJECTED,
)
BALANCE_AFFECTING_TYPES = {"paid"}
SCHEDULE_BALANCE_STATUSES = (
    VacationScheduleItem.STATUS_PLANNED,
    VacationScheduleItem.STATUS_APPROVED,
)
REQUEST_STATUS_UI = {
    VacationRequest.STATUS_APPROVED: {"label": "Одобрено", "icon": "check_circle", "css_class": "approved"},
    VacationRequest.STATUS_PENDING: {"label": "В ожидании", "icon": "watch_later", "css_class": "pending"},
    VacationRequest.STATUS_REJECTED: {"label": "Отклонено", "icon": "error", "css_class": "rejected"},
}
RUSSIAN_MONTH_NAMES = [
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
]
RUSSIAN_MONTH_SHORT_NAMES = [
    "Янв",
    "Фев",
    "Мар",
    "Апр",
    "Май",
    "Июн",
    "Июл",
    "Авг",
    "Сен",
    "Окт",
    "Ноя",
    "Дек",
]
VACATION_STATUS_META = {
    VacationRequest.STATUS_REJECTED: {"label": "Отклонено", "icon": "error"},
    VacationRequest.STATUS_APPROVED: {"label": "Одобрено", "icon": "check_circle"},
    VacationRequest.STATUS_PENDING: {"label": "В ожидании", "icon": "watch_later"},
    "free": {"label": "Свободно", "icon": "event_available"},
    "mixed": {"label": "Смешанный период", "icon": "layers"},
}
STATUS_PRIORITY = {
    "free": 0,
    VacationRequest.STATUS_REJECTED: 1,
    VacationRequest.STATUS_PENDING: 2,
    VacationRequest.STATUS_APPROVED: 3,
}
WEEKDAY_SHORT_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

LEAVE_DAY_QUANTIZER = Decimal("0.01")
LEAVE_ADVANCE_MONTHS = 6


def get_vacation_requests_queryset():
    return VacationRequest.objects.select_related("employee", "employee__department")


def format_ru_date(value):
    return value.strftime("%d.%m.%Y")


def format_period_label(start_date, end_date):
    return f"{format_ru_date(start_date)} - {format_ru_date(end_date)}"


def add_years_safe(value, years):
    target_year = value.year + years
    last_day = calendar.monthrange(target_year, value.month)[1]
    return value.replace(year=target_year, day=min(value.day, last_day))


def add_months_safe(value, months):
    total_months = (value.year * 12 + (value.month - 1)) + months
    target_year = total_months // 12
    target_month = total_months % 12 + 1
    last_day = calendar.monthrange(target_year, target_month)[1]
    return value.replace(year=target_year, month=target_month, day=min(value.day, last_day))


def quantize_leave_days(value):
    return Decimal(value).quantize(LEAVE_DAY_QUANTIZER, rounding=ROUND_HALF_UP)


def iterate_dates(start_date, end_date):
    current_date = start_date
    while current_date <= end_date:
        yield current_date
        current_date += timedelta(days=1)


def get_month_range(start_date, end_date):
    current_date = start_date.replace(day=1)
    target_date = end_date.replace(day=1)
    while current_date <= target_date:
        yield current_date
        current_date = (current_date + timedelta(days=32)).replace(day=1)


def get_month_end(month_start):
    last_day = calendar.monthrange(month_start.year, month_start.month)[1]
    return month_start.replace(day=last_day)


def clip_period_to_range(start_date, end_date, range_start, range_end):
    clipped_start = max(start_date, range_start)
    clipped_end = min(end_date, range_end)
    if clipped_start > clipped_end:
        return None
    return clipped_start, clipped_end


def get_overlap_days(start_date, end_date, range_start, range_end):
    clipped_period = clip_period_to_range(start_date, end_date, range_start, range_end)
    if clipped_period is None:
        return 0
    clipped_start, clipped_end = clipped_period
    return (clipped_end - clipped_start).days + 1


def get_requested_days(start_date, end_date):
    return (end_date - start_date).days + 1


def get_russian_holiday_dates(start_date, end_date):
    if end_date < start_date:
        return set()

    holiday_dates = set()
    for year in range(start_date.year, end_date.year + 1):
        year_start = date(year, 1, 1)
        year_end = date(year, 12, 31)
        range_start = max(start_date, year_start)
        range_end = min(end_date, year_end)
        if range_start > range_end:
            continue

        holiday_dates.update(
            current_date
            for current_date in _get_russian_holiday_dates_for_year(year)
            if range_start <= current_date <= range_end
        )
    return holiday_dates


def get_russian_holiday_iso_dates(years):
    holiday_dates = set()
    for year in years:
        holiday_dates.update(_get_russian_holiday_dates_for_year(year))
    return sorted(current_date.isoformat() for current_date in holiday_dates)


@lru_cache(maxsize=None)
def _get_russian_holiday_dates_for_year(year):
    holiday_calendar = holidays.country_holidays("RU", years=[year])
    return frozenset(holiday_calendar.keys())


def get_chargeable_leave_days(start_date, end_date, vacation_type):
    if vacation_type not in BALANCE_AFFECTING_TYPES:
        return 0
    holiday_days = len(get_russian_holiday_dates(start_date, end_date))
    return max(get_requested_days(start_date, end_date) - holiday_days, 0)


def get_vacation_day_cost(vacation_type, start_date, end_date):
    return get_chargeable_leave_days(start_date, end_date, vacation_type)


def get_working_year_bounds(employee, as_of_date=None):
    as_of_date = as_of_date or timezone.localdate()
    start_date = employee.date_joined
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


def get_employee_used_paid_days(employee, as_of_date=None):
    as_of_date = as_of_date or timezone.localdate()
    approved_requests = VacationRequest.objects.filter(
        employee=employee,
        status=VacationRequest.STATUS_APPROVED,
        vacation_type__in=BALANCE_AFFECTING_TYPES,
        start_date__lte=as_of_date,
    )
    approved_schedule_items = VacationScheduleItem.objects.filter(
        employee=employee,
        status__in=SCHEDULE_BALANCE_STATUSES,
        vacation_type__in=BALANCE_AFFECTING_TYPES,
        start_date__lte=as_of_date,
    )
    request_days = sum(
        get_chargeable_leave_days(request_obj.start_date, request_obj.end_date, request_obj.vacation_type)
        for request_obj in approved_requests
    )
    schedule_days = sum(item.chargeable_days for item in approved_schedule_items)
    return request_days + schedule_days


def get_employee_reserved_paid_days(employee, as_of_date=None, exclude_request_id=None):
    as_of_date = as_of_date or timezone.localdate()
    pending_requests = VacationRequest.objects.filter(
        employee=employee,
        status__in=(VacationRequest.STATUS_PENDING, VacationRequest.STATUS_APPROVED),
        vacation_type__in=BALANCE_AFFECTING_TYPES,
    )
    pending_requests = pending_requests.filter(
        models.Q(status=VacationRequest.STATUS_PENDING) | models.Q(start_date__gt=as_of_date)
    )
    if exclude_request_id is not None:
        pending_requests = pending_requests.exclude(pk=exclude_request_id)
    request_days = sum(get_chargeable_leave_days(request_obj.start_date, request_obj.end_date, request_obj.vacation_type) for request_obj in pending_requests)
    planned_schedule_items = VacationScheduleItem.objects.filter(
        employee=employee,
        status__in=SCHEDULE_BALANCE_STATUSES,
        vacation_type__in=BALANCE_AFFECTING_TYPES,
        start_date__gt=as_of_date,
    )
    return request_days + sum(item.chargeable_days for item in planned_schedule_items)


def get_employee_accrued_leave(employee, as_of_date=None):
    as_of_date = as_of_date or timezone.localdate()
    if as_of_date < employee.date_joined:
        return Decimal("0.00")

    annual_leave = Decimal(employee.annual_paid_leave_days)
    working_year_start, working_year_end = get_working_year_bounds(employee, as_of_date)
    completed_years = max(0, working_year_start.year - employee.date_joined.year)
    # Correct for employees hired on leap dates or near month boundaries.
    while add_years_safe(employee.date_joined, completed_years) > working_year_start:
        completed_years -= 1

    fully_accrued = annual_leave * completed_years
    elapsed_days = (min(as_of_date, working_year_end) - working_year_start).days + 1
    working_year_days = (working_year_end - working_year_start).days + 1
    current_year_accrued = annual_leave * Decimal(elapsed_days) / Decimal(working_year_days)
    return quantize_leave_days(fully_accrued + current_year_accrued)


def get_employee_requestable_leave(employee, as_of_date=None):
    as_of_date = as_of_date or timezone.localdate()
    if as_of_date < employee.date_joined:
        return Decimal("0.00")

    annual_leave = Decimal(employee.annual_paid_leave_days)
    working_year_start, working_year_end = get_working_year_bounds(employee, as_of_date)
    completed_years = max(0, working_year_start.year - employee.date_joined.year)
    while add_years_safe(employee.date_joined, completed_years) > working_year_start:
        completed_years -= 1

    fully_requestable = annual_leave * completed_years
    current_year_accrued = get_employee_accrued_leave(employee, as_of_date) - quantize_leave_days(annual_leave * completed_years)
    if completed_years == 0:
        first_year_advance_available_from = add_months_safe(employee.date_joined, LEAVE_ADVANCE_MONTHS)
        current_year_requestable = annual_leave if as_of_date >= first_year_advance_available_from else current_year_accrued
    else:
        current_year_requestable = annual_leave
    return quantize_leave_days(fully_requestable + current_year_requestable)


def get_employee_available_balance(employee, as_of_date=None, exclude_request_id=None):
    requestable_days = get_employee_requestable_leave(employee, as_of_date)
    used_days = Decimal(get_employee_used_paid_days(employee, as_of_date))
    reserved_days = Decimal(get_employee_reserved_paid_days(employee, as_of_date, exclude_request_id=exclude_request_id))
    adjustments = Decimal(employee.manual_leave_adjustment_days)
    available = requestable_days + adjustments - used_days - reserved_days
    return quantize_leave_days(max(available, Decimal("0")))


def _build_employee_leave_summary(employee, as_of_date, used_days, reserved_days):
    annual_entitlement = quantize_leave_days(employee.annual_paid_leave_days)
    accrued = get_employee_accrued_leave(employee, as_of_date)
    requestable = get_employee_requestable_leave(employee, as_of_date)
    used = quantize_leave_days(used_days)
    reserved = quantize_leave_days(reserved_days)
    manual_adjustment = quantize_leave_days(employee.manual_leave_adjustment_days)
    accrued_balance = quantize_leave_days(accrued + manual_adjustment - used - reserved)
    available = quantize_leave_days(
        max(
            requestable + manual_adjustment - used - reserved,
            Decimal("0"),
        )
    )
    advance_available = quantize_leave_days(max(available - max(accrued_balance, Decimal("0")), Decimal("0")))
    return {
        "annual_entitlement": annual_entitlement,
        "accrued": accrued,
        "requestable": requestable,
        "reserved": reserved,
        "used": used,
        "accrued_balance": accrued_balance,
        "advance_available": advance_available,
        "available": available,
        "manual_adjustment": manual_adjustment,
    }


def get_employee_leave_summary(employee, as_of_date=None):
    as_of_date = as_of_date or timezone.localdate()
    used_days = Decimal(get_employee_used_paid_days(employee, as_of_date))
    reserved_days = Decimal(get_employee_reserved_paid_days(employee, as_of_date))
    return _build_employee_leave_summary(employee, as_of_date, used_days, reserved_days)


def get_employee_leave_summaries(employees, as_of_date=None):
    as_of_date = as_of_date or timezone.localdate()
    employees = list(employees)
    if not employees:
        return {}

    usage_by_employee = {
        employee.id: {
            VacationRequest.STATUS_APPROVED: Decimal("0"),
            VacationRequest.STATUS_PENDING: Decimal("0"),
        }
        for employee in employees
    }

    balance_requests = VacationRequest.objects.filter(
        employee_id__in=usage_by_employee.keys(),
        vacation_type__in=BALANCE_AFFECTING_TYPES,
        status__in=ACTIVE_REQUEST_STATUSES,
    ).values("employee_id", "status", "start_date", "end_date", "vacation_type")
    balance_schedule_items = VacationScheduleItem.objects.filter(
        employee_id__in=usage_by_employee.keys(),
        vacation_type__in=BALANCE_AFFECTING_TYPES,
        status__in=SCHEDULE_BALANCE_STATUSES,
    ).values("employee_id", "start_date", "chargeable_days")

    for request_obj in balance_requests:
        chargeable_days = Decimal(
            get_chargeable_leave_days(
                request_obj["start_date"],
                request_obj["end_date"],
                request_obj["vacation_type"],
            )
        )
        status_key = (
            VacationRequest.STATUS_PENDING
            if request_obj["status"] == VacationRequest.STATUS_APPROVED and request_obj["start_date"] > as_of_date
            else request_obj["status"]
        )
        usage_by_employee[request_obj["employee_id"]][status_key] += chargeable_days

    for item in balance_schedule_items:
        status_key = (
            VacationRequest.STATUS_APPROVED
            if item["start_date"] <= as_of_date
            else VacationRequest.STATUS_PENDING
        )
        usage_by_employee[item["employee_id"]][status_key] += Decimal(item["chargeable_days"])

    return {
        employee.id: _build_employee_leave_summary(
            employee,
            as_of_date,
            usage_by_employee[employee.id][VacationRequest.STATUS_APPROVED],
            usage_by_employee[employee.id][VacationRequest.STATUS_PENDING],
        )
        for employee in employees
    }


def get_employee_list_leave_summaries(employees, as_of_date=None):
    as_of_date = as_of_date or timezone.localdate()
    employees = list(employees)
    if not employees:
        return {}

    reserved_by_employee = {
        employee.id: Decimal("0")
        for employee in employees
    }

    pending_requests = VacationRequest.objects.filter(
        employee_id__in=reserved_by_employee.keys(),
        vacation_type__in=BALANCE_AFFECTING_TYPES,
        status=VacationRequest.STATUS_PENDING,
    ).values("employee_id", "start_date", "end_date", "vacation_type")
    approved_requests = VacationRequest.objects.filter(
        employee_id__in=reserved_by_employee.keys(),
        vacation_type__in=BALANCE_AFFECTING_TYPES,
        status=VacationRequest.STATUS_APPROVED,
    ).values("employee_id", "start_date", "end_date", "vacation_type")
    used_schedule_items = VacationScheduleItem.objects.filter(
        employee_id__in=reserved_by_employee.keys(),
        vacation_type__in=BALANCE_AFFECTING_TYPES,
        status__in=SCHEDULE_BALANCE_STATUSES,
    ).values("employee_id", "start_date", "chargeable_days")
    used_by_employee = {
        employee.id: Decimal("0")
        for employee in employees
    }

    for request_obj in pending_requests:
        reserved_by_employee[request_obj["employee_id"]] += Decimal(
            get_chargeable_leave_days(
                request_obj["start_date"],
                request_obj["end_date"],
                request_obj["vacation_type"],
            )
        )

    for request_obj in approved_requests:
        chargeable_days = Decimal(
            get_chargeable_leave_days(
                request_obj["start_date"],
                request_obj["end_date"],
                request_obj["vacation_type"],
            )
        )
        if request_obj["start_date"] <= as_of_date:
            used_by_employee[request_obj["employee_id"]] += chargeable_days
        else:
            reserved_by_employee[request_obj["employee_id"]] += chargeable_days

    for item in used_schedule_items:
        if item["start_date"] <= as_of_date:
            used_by_employee[item["employee_id"]] += Decimal(item["chargeable_days"])
        else:
            reserved_by_employee[item["employee_id"]] += Decimal(item["chargeable_days"])

    summaries = {}
    for employee in employees:
        annual_entitlement = quantize_leave_days(employee.annual_paid_leave_days)
        accrued = get_employee_accrued_leave(employee, as_of_date)
        requestable = get_employee_requestable_leave(employee, as_of_date)
        used = quantize_leave_days(used_by_employee[employee.id])
        reserved = quantize_leave_days(reserved_by_employee[employee.id])
        manual_adjustment = quantize_leave_days(employee.manual_leave_adjustment_days)
        accrued_balance = quantize_leave_days(accrued + manual_adjustment - used - reserved)
        available = quantize_leave_days(
            max(
                requestable + manual_adjustment - used - reserved,
                Decimal("0"),
            )
        )
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


def get_employee_remaining_balance(employee):
    return get_employee_available_balance(employee)


def get_overlapping_requests(employee, start_date, end_date, exclude_request_id=None, statuses=None):
    if statuses is None:
        statuses = ACTIVE_REQUEST_STATUSES

    queryset = VacationRequest.objects.filter(
        employee=employee,
        status__in=statuses,
        start_date__lte=end_date,
        end_date__gte=start_date,
    )
    if exclude_request_id is not None:
        queryset = queryset.exclude(pk=exclude_request_id)
    return queryset


def validate_vacation_request_for_employee(employee, start_date, end_date, vacation_type, exclude_request_id=None):
    if end_date < start_date:
        raise ValidationError("Дата окончания не может быть раньше даты начала.")

    overlaps_existing = get_overlapping_requests(
        employee=employee,
        start_date=start_date,
        end_date=end_date,
        exclude_request_id=exclude_request_id,
    ).exists()
    if overlaps_existing:
        raise ValidationError("На выбранные даты уже есть активная заявка или одобренный отпуск.")

    requested_cost = get_vacation_day_cost(vacation_type, start_date, end_date)
    if requested_cost > get_employee_available_balance(employee, exclude_request_id=exclude_request_id):
        raise ValidationError("Выбранный отпуск превышает доступный баланс дней.")


def create_vacation_request(employee, start_date, end_date, vacation_type):
    validate_vacation_request_for_employee(employee, start_date, end_date, vacation_type)
    return VacationRequest.objects.create(
        employee=employee,
        start_date=start_date,
        end_date=end_date,
        vacation_type=vacation_type,
        status=VacationRequest.STATUS_PENDING,
    )


def enrich_vacation_request(request_obj):
    status_meta = REQUEST_STATUS_UI[request_obj.status]
    request_obj.status_label = status_meta["label"]
    request_obj.status_icon = status_meta["icon"]
    request_obj.status_css_class = status_meta["css_class"]
    request_obj.request_type = {
        VacationRequest.STATUS_APPROVED: "vacation",
        VacationRequest.STATUS_PENDING: "pre_holiday",
        VacationRequest.STATUS_REJECTED: "canceled_holiday",
    }[request_obj.status]
    request_obj.start_date_formatted = date_format(request_obj.start_date, "j E Y")
    request_obj.end_date_formatted = date_format(request_obj.end_date, "j E Y")
    return request_obj


def serialize_vacation_request_row(request_obj):
    enrich_vacation_request(request_obj)
    return {
        "id": request_obj.id,
        "employee_name": request_obj.employee.full_name,
        "start_date_formatted": request_obj.start_date_formatted,
        "end_date_formatted": request_obj.end_date_formatted,
        "vacation_type_label": request_obj.get_vacation_type_display(),
        "status": request_obj.status,
        "status_label": request_obj.status_label,
        "status_icon": request_obj.status_icon,
        "status_css_class": request_obj.status_css_class,
    }


def get_employee_vacation_requests(employee):
    requests = list(get_vacation_requests_queryset().filter(employee=employee).order_by("-created_at"))
    return [enrich_vacation_request(request_obj) for request_obj in requests]


def sync_employee_vacation_metrics(employee):
    if employee is None:
        return

    today = timezone.localdate()
    approved_requests = VacationRequest.objects.filter(
        employee=employee,
        status=VacationRequest.STATUS_APPROVED,
    )
    active_schedule_items = VacationScheduleItem.objects.filter(
        employee=employee,
        status__in=SCHEDULE_BALANCE_STATUSES,
        start_date__lte=today,
        end_date__gte=today,
    )
    used_up_days = get_employee_used_paid_days(employee, today)
    employee.used_up_days = max(used_up_days, 0)
    employee.vacation_days = employee.annual_paid_leave_days
    employee.is_working = not (
        approved_requests.filter(start_date__lte=today, end_date__gte=today).exists()
        or active_schedule_items.exists()
    )
    employee.save(update_fields=["used_up_days", "vacation_days", "is_working"])


@transaction.atomic
def approve_vacation_request(vacation_id):
    vacation = VacationRequest.objects.select_related("employee").select_for_update().get(pk=vacation_id)
    if vacation.status != VacationRequest.STATUS_PENDING:
        raise ValidationError("Одобрить можно только заявку со статусом 'В ожидании'.")

    employee = Employees.objects.select_for_update().get(pk=vacation.employee_id)
    validate_vacation_request_for_employee(
        employee=employee,
        start_date=vacation.start_date,
        end_date=vacation.end_date,
        vacation_type=vacation.vacation_type,
        exclude_request_id=vacation.id,
    )
    vacation.status = VacationRequest.STATUS_APPROVED
    vacation.save(update_fields=["status"])
    sync_employee_vacation_metrics(employee)
    return vacation


@transaction.atomic
def reject_vacation_request(vacation_id):
    vacation = VacationRequest.objects.select_related("employee").select_for_update().get(pk=vacation_id)
    if vacation.status != VacationRequest.STATUS_PENDING:
        raise ValidationError("Отклонить можно только заявку со статусом 'В ожидании'.")

    vacation.status = VacationRequest.STATUS_REJECTED
    vacation.save(update_fields=["status"])
    sync_employee_vacation_metrics(vacation.employee)
    return vacation


@transaction.atomic
def delete_pending_vacation_request(vacation_id):
    vacation = VacationRequest.objects.select_related("employee").select_for_update().get(pk=vacation_id)
    if vacation.status != VacationRequest.STATUS_PENDING:
        raise ValidationError("Удалить можно только заявку со статусом 'В ожидании'.")

    employee = vacation.employee
    vacation.delete()
    sync_employee_vacation_metrics(employee)
    return employee


def get_calendar_redirect_url(request):
    next_view = request.POST.get("next_view_mode", request.GET.get("view", "month"))
    next_year = request.POST.get("next_year", request.GET.get("year", timezone.localdate().year))
    next_month = request.POST.get("next_month", request.GET.get("month", timezone.localdate().month))
    return f"{request.path}?view={next_view}&year={next_year}&month={next_month}"


def build_calendar_base_data(year, employee_ids=None):
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    employees_queryset = Employees.objects.select_related("department").filter(is_active_employee=True).order_by(
        "last_name",
        "first_name",
        "middle_name",
    )
    if employee_ids is not None:
        employees_queryset = employees_queryset.filter(id__in=employee_ids)

    employees = list(employees_queryset)
    employee_day_status = {employee.id: {} for employee in employees}
    employee_entries = {employee.id: [] for employee in employees}

    records = get_vacation_requests_queryset().filter(
        start_date__lte=year_end,
        end_date__gte=year_start,
        status__in=CALENDAR_VISIBLE_STATUSES,
    )
    if employee_ids is not None:
        records = records.filter(employee_id__in=employee_ids)

    for record in records:
        clipped_period = clip_period_to_range(record.start_date, record.end_date, year_start, year_end)
        if clipped_period is None:
            continue

        clipped_start, clipped_end = clipped_period
        employee = record.employee
        entry = {
            "employee_id": employee.id,
            "employee_name": employee.full_name,
            "employee_position": employee.position,
            "department_name": employee.department.name if employee.department else "Не указан",
            "status": record.status,
            "status_label": REQUEST_STATUS_UI[record.status]["label"],
            "status_icon": REQUEST_STATUS_UI[record.status]["icon"],
            "vacation_type_label": record.get_vacation_type_display(),
            "start_date": clipped_start,
            "end_date": clipped_end,
            "days": get_requested_days(clipped_start, clipped_end),
            "period_label": format_period_label(clipped_start, clipped_end),
            "sort_key": clipped_start.toordinal(),
        }
        employee_entries[employee.id].append(entry)

        for current_date in iterate_dates(clipped_start, clipped_end):
            current_status = employee_day_status[employee.id].get(current_date, "free")
            if STATUS_PRIORITY[record.status] >= STATUS_PRIORITY[current_status]:
                employee_day_status[employee.id][current_date] = record.status

    for employee_id, entries in employee_entries.items():
        entries.sort(key=lambda item: (item["sort_key"], -STATUS_PRIORITY[item["status"]]))

    return employees, employee_day_status, employee_entries


def build_month_timeline_cells(day_map, year, month, today):
    days_in_month = calendar.monthrange(year, month)[1]
    cells = []
    for day in range(1, days_in_month + 1):
        current_date = date(year, month, day)
        status = day_map.get(current_date, "free")
        previous_status = day_map.get(current_date - timedelta(days=1), "free") if day > 1 else "free"
        next_status = day_map.get(current_date + timedelta(days=1), "free") if day < days_in_month else "free"
        is_start = status != "free" and previous_status != status
        is_end = status != "free" and next_status != status
        cells.append(
            {
                "day": day,
                "status": status,
                "is_weekend": current_date.weekday() >= 5,
                "is_today": current_date == today,
                "is_start": is_start,
                "is_end": is_end,
                "is_single": is_start and is_end,
                "tooltip": f'{day:02d}.{month:02d}.{year} • {VACATION_STATUS_META[status]["label"]}',
            }
        )
    return cells


def build_year_month_cells(entries, year):
    month_cells = []
    for month_number in range(1, 13):
        month_start = date(year, month_number, 1)
        month_end = get_month_end(month_start)
        days_in_month = calendar.monthrange(year, month_number)[1]
        counts = {
            VacationRequest.STATUS_APPROVED: 0,
            VacationRequest.STATUS_PENDING: 0,
            VacationRequest.STATUS_REJECTED: 0,
        }
        segments = []
        for entry in entries:
            overlap = clip_period_to_range(entry["start_date"], entry["end_date"], month_start, month_end)
            if overlap is None:
                continue

            overlap_start, overlap_end = overlap
            overlap_days = get_requested_days(overlap_start, overlap_end)
            if entry["status"] in counts:
                counts[entry["status"]] += overlap_days

            segments.append(
                {
                    "status": entry["status"],
                    "days": overlap_days,
                    "offset_percent": round(((overlap_start.day - 1) / days_in_month) * 100, 1),
                    "width_percent": round((overlap_days / days_in_month) * 100, 1),
                }
            )

        busy_days = (
            counts[VacationRequest.STATUS_APPROVED]
            + counts[VacationRequest.STATUS_PENDING]
            + counts[VacationRequest.STATUS_REJECTED]
        )
        active_statuses = [status for status, value in counts.items() if value]
        if len(active_statuses) > 1:
            status_key = "mixed"
        elif active_statuses:
            status_key = active_statuses[0]
        else:
            status_key = "free"

        segments.sort(
            key=lambda segment: (
                segment["offset_percent"],
                -STATUS_PRIORITY.get(segment["status"], 0),
            )
        )

        month_cells.append(
            {
                "month_name": RUSSIAN_MONTH_NAMES[month_number - 1],
                "month_short": RUSSIAN_MONTH_SHORT_NAMES[month_number - 1],
                "busy_days": busy_days,
                "status": status_key,
                "segments": segments,
                "approved_days": counts[VacationRequest.STATUS_APPROVED],
                "pending_days": counts[VacationRequest.STATUS_PENDING],
                "rejected_days": counts[VacationRequest.STATUS_REJECTED],
            }
        )

    return month_cells


def build_calendar_rows(employees, employee_day_status, employee_entries, year, month, view_mode, today):
    period_start = date(year, 1, 1) if view_mode == "year" else date(year, month, 1)
    period_end = date(year, 12, 31) if view_mode == "year" else date(year, month, calendar.monthrange(year, month)[1])
    rows = []
    details = {}

    for employee in employees:
        day_map = employee_day_status.get(employee.id, {})
        entries = employee_entries.get(employee.id, [])

        period_counts = {
            VacationRequest.STATUS_APPROVED: 0,
            VacationRequest.STATUS_PENDING: 0,
            VacationRequest.STATUS_REJECTED: 0,
        }
        year_counts = {
            VacationRequest.STATUS_APPROVED: 0,
            VacationRequest.STATUS_PENDING: 0,
            VacationRequest.STATUS_REJECTED: 0,
        }
        for current_date, status in day_map.items():
            if status in year_counts:
                year_counts[status] += 1
                if period_start <= current_date <= period_end:
                    period_counts[status] += 1

        selected_entries = [
            entry for entry in entries if clip_period_to_range(entry["start_date"], entry["end_date"], period_start, period_end)
        ]
        upcoming_entry = next((entry for entry in entries if entry["end_date"] >= today), None)

        row_statuses = [
            status
            for status in (
                VacationRequest.STATUS_APPROVED,
                VacationRequest.STATUS_PENDING,
                VacationRequest.STATUS_REJECTED,
            )
            if period_counts[status]
        ]
        row_status = "mixed" if len(row_statuses) > 1 else row_statuses[0] if row_statuses else "free"

        rows.append(
            {
                "employee_id": employee.id,
                "employee_name": employee.full_name,
                "position": employee.position,
                "department": employee.department.name if employee.department else "Не указан",
                "status": row_status,
                "selected_approved_days": period_counts[VacationRequest.STATUS_APPROVED],
                "selected_pending_days": period_counts[VacationRequest.STATUS_PENDING],
                "selected_rejected_days": period_counts[VacationRequest.STATUS_REJECTED],
                "year_approved_days": year_counts[VacationRequest.STATUS_APPROVED],
                "year_pending_days": year_counts[VacationRequest.STATUS_PENDING],
                "year_rejected_days": year_counts[VacationRequest.STATUS_REJECTED],
                "cells": build_year_month_cells(entries, year)
                if view_mode == "year"
                else build_month_timeline_cells(day_map, year, month, today),
            }
        )

        details[str(employee.id)] = {
            "employee_name": employee.full_name,
            "position": employee.position,
            "department": employee.department.name if employee.department else "Не указан",
            "selected_period_label": f"{RUSSIAN_MONTH_NAMES[month - 1]} {year}" if view_mode == "month" else f"Годовой обзор {year}",
            "selected_approved_days": period_counts[VacationRequest.STATUS_APPROVED],
            "selected_pending_days": period_counts[VacationRequest.STATUS_PENDING],
            "selected_rejected_days": period_counts[VacationRequest.STATUS_REJECTED],
            "year_approved_days": year_counts[VacationRequest.STATUS_APPROVED],
            "year_pending_days": year_counts[VacationRequest.STATUS_PENDING],
            "year_rejected_days": year_counts[VacationRequest.STATUS_REJECTED],
            "upcoming_label": upcoming_entry["period_label"] if upcoming_entry else "Ближайший отпуск не запланирован",
            "upcoming_status": upcoming_entry["status_label"] if upcoming_entry else "",
            "selected_entries": [
                {
                    "period_label": entry["period_label"],
                    "status_label": entry["status_label"],
                    "status": entry["status"],
                    "vacation_type_label": entry["vacation_type_label"],
                    "days": entry["days"],
                }
                for entry in selected_entries
            ],
            "year_entries": [
                {
                    "period_label": entry["period_label"],
                    "status_label": entry["status_label"],
                    "status": entry["status"],
                    "vacation_type_label": entry["vacation_type_label"],
                    "days": entry["days"],
                }
                for entry in entries
            ],
        }

    return rows, details


def build_calendar_summary(employee_entries, year, month, view_mode):
    period_start = date(year, 1, 1) if view_mode == "year" else date(year, month, 1)
    period_end = date(year, 12, 31) if view_mode == "year" else date(year, month, calendar.monthrange(year, month)[1])
    employees_in_period = set()
    counts = {
        VacationRequest.STATUS_APPROVED: 0,
        VacationRequest.STATUS_PENDING: 0,
    }

    for entries in employee_entries.values():
        for entry in entries:
            overlap = clip_period_to_range(entry["start_date"], entry["end_date"], period_start, period_end)
            if overlap is None:
                continue

            overlap_start, overlap_end = overlap
            overlap_days = get_requested_days(overlap_start, overlap_end)
            employees_in_period.add(entry["employee_id"])
            if entry["status"] in counts:
                counts[entry["status"]] += overlap_days

    employees_count = len(employees_in_period)
    approved_days = counts[VacationRequest.STATUS_APPROVED]
    pending_days = counts[VacationRequest.STATUS_PENDING]

    return [
        {
            "icon": "groups",
            "label": "Сотрудников в периоде",
            "value": employees_count,
            "hint": "У кого есть отпуск или заявка в выбранном диапазоне.",
        },
        {
            "icon": "event_available",
            "label": "Одобрено дней",
            "value": approved_days,
            "hint": "Все подтверждённые дни отпуска за выбранный период.",
        },
        {
            "icon": "watch_later",
            "label": "В ожидании дней",
            "value": pending_days,
            "hint": "Дни по заявкам, которые ещё ждут решения.",
        },
    ]


def build_analytics_payload(employee_ids=None):
    year = timezone.localdate().year
    employees, employee_day_status, employee_entries = build_calendar_base_data(year, employee_ids=employee_ids)
    rows, _ = build_calendar_rows(
        employees,
        employee_day_status,
        employee_entries,
        year=year,
        month=timezone.localdate().month,
        view_mode="year",
        today=timezone.localdate(),
    )

    vacation_counts = [0] * 12
    average_duration_days = [0] * 12
    planned_days = [0] * 12
    duration_totals = [0] * 12
    for entries in employee_entries.values():
        for entry in entries:
            for month_start in get_month_range(entry["start_date"], entry["end_date"]):
                overlap_days = get_overlap_days(entry["start_date"], entry["end_date"], month_start, get_month_end(month_start))
                month_index = month_start.month - 1
                vacation_counts[month_index] += 1
                duration_totals[month_index] += overlap_days
                planned_days[month_index] += overlap_days

    for month_index, vacations_in_month in enumerate(vacation_counts):
        if vacations_in_month:
            average_duration_days[month_index] = round(duration_totals[month_index] / vacations_in_month, 2)

    total_employees = len(employees)
    employees_not_on_vacation_count = sum(1 for employee in employees if employee.is_working)
    working_employees = round((employees_not_on_vacation_count / total_employees) * 100) if total_employees else 0
    total_applications_count = VacationRequest.objects.count() if employee_ids is None else VacationRequest.objects.filter(employee_id__in=employee_ids).count()
    canceled_count = (
        VacationRequest.objects.filter(status=VacationRequest.STATUS_REJECTED).count()
        if employee_ids is None
        else VacationRequest.objects.filter(employee_id__in=employee_ids, status=VacationRequest.STATUS_REJECTED).count()
    )
    rejection_percentage = round((canceled_count / total_applications_count) * 100) if total_applications_count else 0
    avg_vacation_days = round(
        sum(employee.annual_paid_leave_days for employee in employees) / total_employees,
        2,
    ) if total_employees else 0

    return {
        "labels": RUSSIAN_MONTH_SHORT_NAMES,
        "values1": vacation_counts,
        "values2": average_duration_days,
        "values3": planned_days,
        "rows": rows,
        "total_employees": total_employees,
        "employees_not_on_vacation_count": employees_not_on_vacation_count,
        "working_employees": working_employees,
        "total_applications_count": total_applications_count,
        "canceled_count": canceled_count,
        "rejection_percentage": rejection_percentage,
        "avg_vacation_days": avg_vacation_days,
    }
