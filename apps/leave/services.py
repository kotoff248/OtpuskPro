import calendar
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateformat import format as date_format

from apps.employees.models import Employees
from apps.leave.models import VacationRequest


ACTIVE_REQUEST_STATUSES = (
    VacationRequest.STATUS_PENDING,
    VacationRequest.STATUS_APPROVED,
)
BALANCE_AFFECTING_TYPES = {"paid"}
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
    VacationRequest.STATUS_APPROVED: {"label": "Одобрено", "icon": "check_circle"},
    VacationRequest.STATUS_PENDING: {"label": "В ожидании", "icon": "watch_later"},
    "free": {"label": "Свободно", "icon": "event_available"},
    "mixed": {"label": "Смешанный период", "icon": "layers"},
}
STATUS_PRIORITY = {
    "free": 0,
    VacationRequest.STATUS_PENDING: 1,
    VacationRequest.STATUS_APPROVED: 2,
}
WEEKDAY_SHORT_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def get_vacation_requests_queryset():
    return VacationRequest.objects.select_related("employee", "employee__department")


def format_ru_date(value):
    return value.strftime("%d.%m.%Y")


def format_period_label(start_date, end_date):
    return f"{format_ru_date(start_date)} - {format_ru_date(end_date)}"


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


def get_vacation_day_cost(vacation_type, start_date, end_date):
    if vacation_type not in BALANCE_AFFECTING_TYPES:
        return 0
    return get_requested_days(start_date, end_date)


def get_employee_remaining_balance(employee):
    return max(employee.vacation_days - employee.used_up_days, 0)


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
    if requested_cost > get_employee_remaining_balance(employee):
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
    used_up_days = 0
    for request_obj in approved_requests:
        if request_obj.vacation_type in BALANCE_AFFECTING_TYPES:
            used_up_days += get_requested_days(request_obj.start_date, request_obj.end_date)

    employee.used_up_days = max(used_up_days, 0)
    employee.is_working = not approved_requests.filter(start_date__lte=today, end_date__gte=today).exists()
    employee.save(update_fields=["used_up_days", "is_working"])


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


def build_calendar_base_data(year):
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    employees = list(Employees.objects.select_related("department").order_by("last_name", "first_name", "middle_name"))
    employee_day_status = {employee.id: {} for employee in employees}
    employee_entries = {employee.id: [] for employee in employees}

    records = get_vacation_requests_queryset().filter(
        start_date__lte=year_end,
        end_date__gte=year_start,
        status__in=ACTIVE_REQUEST_STATUSES,
    )

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
                "selected_rejected_days": 0,
                "year_approved_days": year_counts[VacationRequest.STATUS_APPROVED],
                "year_pending_days": year_counts[VacationRequest.STATUS_PENDING],
                "year_rejected_days": 0,
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
            "selected_rejected_days": 0,
            "year_approved_days": year_counts[VacationRequest.STATUS_APPROVED],
            "year_pending_days": year_counts[VacationRequest.STATUS_PENDING],
            "year_rejected_days": 0,
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


def build_analytics_payload():
    year = timezone.localdate().year
    employees, employee_day_status, employee_entries = build_calendar_base_data(year)
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

    return {
        "labels": RUSSIAN_MONTH_SHORT_NAMES,
        "values1": vacation_counts,
        "values2": average_duration_days,
        "values3": planned_days,
        "rows": rows,
    }
