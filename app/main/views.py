import calendar
import json
from datetime import date, datetime, timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login as auth_login, logout as auth_logout, update_session_auth_hash
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import Group, User
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateformat import format
from django.utils.formats import date_format
from django.utils.http import url_has_allowed_host_and_scheme

from .models import Departments, Employees, VacationRequest


MANAGERS_GROUP_NAME = "Managers"
DJANGO_HASH_PREFIXES = ("pbkdf2_", "argon2$", "bcrypt$", "scrypt$")
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
RUSSIAN_MONTH_SHORT_NAMES = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]
VACATION_STATUS_META = {
    VacationRequest.STATUS_APPROVED: {"label": "Одобрено", "icon": "check_circle"},
    VacationRequest.STATUS_PENDING: {"label": "В ожидании", "icon": "watch_later"},
    VacationRequest.STATUS_REJECTED: {"label": "Отклонено", "icon": "error"},
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


def index(request):
    return render(request, "main/index.html")


def is_django_password_hash(value):
    return bool(value) and value.startswith(DJANGO_HASH_PREFIXES)


def get_manager_group():
    group, _ = Group.objects.get_or_create(name=MANAGERS_GROUP_NAME)
    return group


def is_manager_user(user):
    return user.is_authenticated and user.groups.filter(name=MANAGERS_GROUP_NAME).exists()


def build_employee_username(employee):
    return f"employee_{employee.pk}"


def sync_employee_user(employee, raw_password=None):
    original_user_id = employee.user_id
    user = employee.user
    if user is None:
        user, _ = User.objects.get_or_create(
            username=build_employee_username(employee),
            defaults={"first_name": employee.name[:150], "is_active": True},
        )
        employee.user = user

    user.first_name = employee.name[:150]
    user.is_active = True
    user.is_staff = employee.is_manager

    if raw_password is not None:
        user.set_password(raw_password)
    elif employee.password:
        if is_django_password_hash(employee.password):
            user.password = employee.password
        else:
            user.set_password(employee.password)
    else:
        user.set_unusable_password()

    user.save()

    manager_group = get_manager_group()
    if employee.is_manager:
        user.groups.add(manager_group)
    else:
        user.groups.remove(manager_group)

    employee_updates = []
    if original_user_id != user.id:
        employee.user = user
        employee_updates.append("user")
    if employee.password != user.password:
        employee.password = user.password
        employee_updates.append("password")
    if employee_updates:
        employee.save(update_fields=employee_updates)

    return user


def get_current_employee(request):
    if not request.user.is_authenticated:
        return None

    employee = getattr(request.user, "employee_profile", None)
    if employee is None:
        employee = Employees.objects.filter(user=request.user).first()
    return employee


def get_vacation_requests_queryset():
    return VacationRequest.objects.select_related("employee", "employee__department")


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
    return request_obj


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
        used_up_days += (request_obj.end_date - request_obj.start_date).days + 1

    employee.used_up_days = max(used_up_days, 0)
    employee.is_working = not approved_requests.filter(start_date__lte=today, end_date__gte=today).exists()
    employee.save(update_fields=["used_up_days", "is_working"])


def get_user_context(request):
    employee = get_current_employee(request)
    employee_name = employee.name if employee else request.user.get_username()
    is_manager = is_manager_user(request.user)
    name_parts = employee_name.split()
    last_name = name_parts[0] if name_parts else ""
    initials = "".join(f"{name[0].upper()}." for name in name_parts[1:])
    role = "руководитель" if is_manager else "сотрудник"
    return {
        "employee_name": employee_name,
        "last_name": last_name,
        "initials": initials,
        "role": role,
        "is_manager": is_manager,
    }


def update_context_with_departments(request, context):
    departments = Departments.objects.all()
    if request.method == "POST" and "department" in request.POST:
        request.session["selected_department"] = request.POST.get("department", "all")

    context.update(
        {
            "departments": departments,
            "selected_department": request.session.get("selected_department", "all"),
        }
    )
    return context


def manager_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if is_manager_user(request.user):
            return view_func(request, *args, **kwargs)

        messages.error(request, "У вас нет прав для доступа к этой странице.")
        return redirect("main")

    return _wrapped_view


def employee_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        employee = get_current_employee(request)
        if request.user.is_authenticated and employee is not None:
            return view_func(request, *args, **kwargs)

        if request.user.is_authenticated:
            auth_logout(request)
        return redirect("login")

    return _wrapped_view


def format_ru_date(value):
    return value.strftime("%d.%m.%Y")


def format_period_label(start_date, end_date):
    return f"{format_ru_date(start_date)} - {format_ru_date(end_date)}"


def clip_period_to_range(start_date, end_date, range_start, range_end):
    clipped_start = max(start_date, range_start)
    clipped_end = min(end_date, range_end)
    if clipped_start > clipped_end:
        return None
    return clipped_start, clipped_end


def iterate_dates(start_date, end_date):
    current_date = start_date
    while current_date <= end_date:
        yield current_date
        current_date += timedelta(days=1)


def get_calendar_redirect_url(request):
    next_view = request.POST.get("next_view_mode", request.GET.get("view", "month"))
    next_year = request.POST.get("next_year", request.GET.get("year", timezone.localdate().year))
    next_month = request.POST.get("next_month", request.GET.get("month", timezone.localdate().month))
    return f"{request.path}?view={next_view}&year={next_year}&month={next_month}"


def serialize_vacation_request_row(request_obj):
    enrich_vacation_request(request_obj)
    request_obj.start_date_formatted = format(request_obj.start_date, "j E Y")
    request_obj.end_date_formatted = format(request_obj.end_date, "j E Y")
    return request_obj


def get_month_range(start_date, end_date):
    current_date = start_date.replace(day=1)
    target_date = end_date.replace(day=1)
    while current_date <= target_date:
        yield current_date
        current_date = (current_date + timedelta(days=32)).replace(day=1)


def build_calendar_base_data(year):
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    employees = list(Employees.objects.select_related("department").order_by("name"))
    employee_day_status = {employee.id: {} for employee in employees}
    employee_entries = {employee.id: [] for employee in employees}

    records = get_vacation_requests_queryset().filter(
        start_date__lte=year_end,
        end_date__gte=year_start,
        status__in=[
            VacationRequest.STATUS_APPROVED,
            VacationRequest.STATUS_PENDING,
            VacationRequest.STATUS_REJECTED,
        ],
    )

    for record in records:
        clipped_period = clip_period_to_range(record.start_date, record.end_date, year_start, year_end)
        if clipped_period is None:
            continue

        clipped_start, clipped_end = clipped_period
        employee = record.employee
        entry = {
            "employee_id": employee.id,
            "employee_name": employee.name,
            "employee_position": employee.position,
            "department_name": employee.department.name if employee.department else "Не указан",
            "status": record.status,
            "status_label": REQUEST_STATUS_UI[record.status]["label"],
            "status_icon": REQUEST_STATUS_UI[record.status]["icon"],
            "vacation_type_label": record.get_vacation_type_display(),
            "start_date": clipped_start,
            "end_date": clipped_end,
            "days": (clipped_end - clipped_start).days + 1,
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


def build_year_month_cells(day_map, year):
    month_cells = []
    for month_number in range(1, 13):
        days_in_month = calendar.monthrange(year, month_number)[1]
        counts = {
            VacationRequest.STATUS_APPROVED: 0,
            VacationRequest.STATUS_PENDING: 0,
            VacationRequest.STATUS_REJECTED: 0,
        }
        for day in range(1, days_in_month + 1):
            status = day_map.get(date(year, month_number, day), "free")
            if status in counts:
                counts[status] += 1

        busy_days = sum(counts.values())
        active_statuses = [status for status, value in counts.items() if value]
        if len(active_statuses) > 1:
            status_key = "mixed"
        elif active_statuses:
            status_key = active_statuses[0]
        else:
            status_key = "free"

        segments = []
        for status in (
            VacationRequest.STATUS_APPROVED,
            VacationRequest.STATUS_PENDING,
            VacationRequest.STATUS_REJECTED,
        ):
            days_count = counts[status]
            if days_count:
                segments.append(
                    {
                        "status": status,
                        "days": days_count,
                        "width": round((days_count / days_in_month) * 100, 1),
                    }
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
                "employee_name": employee.name,
                "position": employee.position,
                "department": employee.department.name if employee.department else "Не указан",
                "status": row_status,
                "selected_approved_days": period_counts[VacationRequest.STATUS_APPROVED],
                "selected_pending_days": period_counts[VacationRequest.STATUS_PENDING],
                "selected_rejected_days": period_counts[VacationRequest.STATUS_REJECTED],
                "year_approved_days": year_counts[VacationRequest.STATUS_APPROVED],
                "year_pending_days": year_counts[VacationRequest.STATUS_PENDING],
                "year_rejected_days": year_counts[VacationRequest.STATUS_REJECTED],
                "cells": build_year_month_cells(day_map, year)
                if view_mode == "year"
                else build_month_timeline_cells(day_map, year, month, today),
            }
        )

        details[str(employee.id)] = {
            "employee_name": employee.name,
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


def build_calendar_summary(employee_entries, year, month, view_mode, today):
    del today

    period_start = date(year, 1, 1) if view_mode == "year" else date(year, month, 1)
    period_end = date(year, 12, 31) if view_mode == "year" else date(year, month, calendar.monthrange(year, month)[1])
    employees_in_period = set()
    counts = {
        VacationRequest.STATUS_APPROVED: 0,
        VacationRequest.STATUS_PENDING: 0,
        VacationRequest.STATUS_REJECTED: 0,
    }
    rejected_requests = 0

    for entries in employee_entries.values():
        for entry in entries:
            overlap = clip_period_to_range(entry["start_date"], entry["end_date"], period_start, period_end)
            if overlap is None:
                continue

            overlap_start, overlap_end = overlap
            overlap_days = (overlap_end - overlap_start).days + 1
            employees_in_period.add(entry["employee_id"])
            if entry["status"] in counts:
                counts[entry["status"]] += overlap_days
            if entry["status"] == VacationRequest.STATUS_REJECTED:
                rejected_requests += 1

    return [
        {
            "icon": "groups",
            "label": "Сотрудников в периоде",
            "value": len(employees_in_period),
            "hint": "Есть отпуск или заявка в выбранном диапазоне",
        },
        {
            "icon": "check_circle",
            "label": "Одобренные дни",
            "value": counts[VacationRequest.STATUS_APPROVED],
            "hint": "Подтвержденные отпуска",
        },
        {
            "icon": "schedule",
            "label": "Дни в ожидании",
            "value": counts[VacationRequest.STATUS_PENDING],
            "hint": "Заявки ждут согласования",
        },
        {
            "icon": "cancel",
            "label": "Отклоненные заявки",
            "value": rejected_requests,
            "hint": "Количество отказов в периоде",
        },
    ]


def login_view(request):
    error = None
    if request.user.is_authenticated:
        if get_current_employee(request) is not None:
            return redirect("main")
        auth_logout(request)

    if request.method == "POST":
        username = request.POST["username"]
        password = request.POST["password"]
        user_type = request.POST["user_type"]

        try:
            employee = Employees.objects.select_related("user").get(name=username)
            user = sync_employee_user(employee)
            password_matches = user.check_password(password)
            if not password_matches:
                legacy_password_matches = employee.password == password
                if not legacy_password_matches:
                    try:
                        legacy_password_matches = check_password(password, employee.password)
                    except ValueError:
                        legacy_password_matches = False

                if legacy_password_matches:
                    user = sync_employee_user(employee, raw_password=password)
                    password_matches = True

            if password_matches:
                if (user_type == "manager" and is_manager_user(user)) or (user_type == "employee" and not is_manager_user(user)):
                    auth_login(request, user)
                    return redirect("main")
                error = "Неправильный тип пользователя"
            else:
                error = "Неверный пароль"
        except Employees.DoesNotExist:
            error = "Пользователь не найден"

    return render(request, "main/login.html", {"error": error})


@employee_required
def main(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    employee = get_current_employee(request)
    is_manager = is_manager_user(request.user)
    all_requests = get_employee_vacation_requests(employee)
    total_balance = employee.vacation_days - employee.used_up_days

    context.update(
        {
            "employee": employee,
            "all_requests": all_requests,
            "total_balance": total_balance,
            "pending_requests_count": VacationRequest.objects.filter(status=VacationRequest.STATUS_PENDING).count(),
            "is_manager": is_manager,
            "can_edit_employee": False,
            "show_manager_fields": is_manager,
        }
    )
    return render(request, "main/main.html", context)


@employee_required
def employee_profile(request, employee_id):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    current_employee = get_current_employee(request)
    current_employee_id = current_employee.id if current_employee else None
    is_manager = is_manager_user(request.user)

    if not is_manager and current_employee_id != employee_id:
        messages.error(request, "У вас нет прав для просмотра чужого профиля.")
        return redirect("main")

    employee = get_object_or_404(Employees, id=employee_id)
    all_requests = get_employee_vacation_requests(employee)
    total_balance = employee.vacation_days - employee.used_up_days

    context.update(
        {
            "employee": employee,
            "all_requests": all_requests,
            "total_balance": total_balance,
            "can_edit_employee": is_manager,
            "show_manager_fields": is_manager,
        }
    )
    return render(request, "main/employee_profile.html", context)


@employee_required
@manager_required
def update_employee(request, employee_id):
    employee = get_object_or_404(Employees, id=employee_id)

    if request.method != "POST":
        return redirect("employee_profile", employee_id=employee_id)

    next_path = request.POST.get("next_path")
    if next_path and url_has_allowed_host_and_scheme(
        next_path,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        redirect_response = redirect(next_path)
    else:
        redirect_response = redirect("employee_profile", employee_id=employee_id)

    department_id = request.POST.get("employee_department")
    password = request.POST.get("employee_password", "").strip()
    employee_name = request.POST.get("employee_name", "").strip()
    employee_position = request.POST.get("employee_position", "").strip()
    employee_date_joined = request.POST.get("employee_date_joined")
    employee_vacation_days = request.POST.get("employee_vacation_days")

    if employee_name:
        employee.name = employee_name
    if employee_position:
        employee.position = employee_position
    if employee_date_joined:
        employee.date_joined = employee_date_joined
    if employee_vacation_days not in (None, ""):
        employee.vacation_days = employee_vacation_days
    if department_id:
        employee.department = get_object_or_404(Departments, id=department_id)
    employee.is_manager = request.POST.get("employee_is_manager") == "on"

    employee.save()
    sync_employee_user(employee, raw_password=password if password else None)
    if password and request.user.pk == employee.user_id and employee.user is not None:
        update_session_auth_hash(request, employee.user)

    messages.success(request, "Данные сотрудника обновлены.")
    return redirect_response


def logout_view(request):
    auth_logout(request)
    return redirect("login")


@employee_required
def graphics(request):
    return _graphics_impl(request)


def _graphics_impl(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    current_user = get_current_employee(request)
    today = timezone.localdate()
    current_year = today.year

    selected_year = request.GET.get("year", current_year)
    selected_month = request.GET.get("month", today.month)
    calendar_view_mode = request.GET.get("view", "month")
    selected_employee_id = request.GET.get("employee")

    try:
        selected_year = int(selected_year)
    except (TypeError, ValueError):
        selected_year = current_year

    try:
        selected_month = int(selected_month)
    except (TypeError, ValueError):
        selected_month = today.month

    try:
        selected_employee_id = int(selected_employee_id) if selected_employee_id else None
    except (TypeError, ValueError):
        selected_employee_id = None

    if selected_month < 1 or selected_month > 12:
        selected_month = today.month
    if calendar_view_mode not in ("year", "month"):
        calendar_view_mode = "month"

    sync_employee_vacation_metrics(current_user)
    current_user.refresh_from_db()
    current_user_final_balance = current_user.vacation_days - current_user.used_up_days

    if request.method == "POST":
        start_date_raw = request.POST.get("start_date", "").strip()
        end_date_raw = request.POST.get("end_date", "").strip()
        vacation_type = request.POST.get("type_vacation", "paid")
        redirect_url = get_calendar_redirect_url(request)

        if not start_date_raw or not end_date_raw:
            messages.error(request, "Выберите даты начала и окончания отпуска.")
            return redirect(redirect_url)

        try:
            start_date = datetime.strptime(start_date_raw, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_raw, "%Y-%m-%d").date()
        except ValueError:
            messages.error(request, "Не удалось обработать выбранные даты.")
            return redirect(redirect_url)

        if end_date < start_date:
            messages.error(request, "Дата окончания не может быть раньше даты начала.")
            return redirect(redirect_url)

        requested_days = (end_date - start_date).days + 1
        if requested_days > current_user_final_balance:
            messages.error(request, "Выбранный отпуск превышает доступный баланс дней.")
            return redirect(redirect_url)

        overlaps_existing = VacationRequest.objects.filter(
            employee=current_user,
            start_date__lte=end_date,
            end_date__gte=start_date,
        ).exists()
        if overlaps_existing:
            messages.error(request, "На выбранные даты уже есть отпуск или заявка.")
            return redirect(redirect_url)

        VacationRequest.objects.create(
            employee=current_user,
            start_date=start_date,
            end_date=end_date,
            vacation_type=vacation_type,
            status=VacationRequest.STATUS_PENDING,
        )
        messages.success(request, "Заявка на отпуск успешно добавлена в график.")
        return redirect(redirect_url)

    employees, employee_day_status, employee_entries = build_calendar_base_data(selected_year)
    calendar_rows, calendar_details = build_calendar_rows(
        employees,
        employee_day_status,
        employee_entries,
        selected_year,
        selected_month,
        calendar_view_mode,
        today,
    )
    calendar_summary = build_calendar_summary(
        employee_entries,
        selected_year,
        selected_month,
        calendar_view_mode,
        today,
    )

    employee_ids = {row["employee_id"] for row in calendar_rows}
    if selected_employee_id not in employee_ids:
        selected_employee_id = current_user.id if current_user and current_user.id in employee_ids else None
    if selected_employee_id not in employee_ids and calendar_rows:
        selected_employee_id = calendar_rows[0]["employee_id"]

    selected_employee_detail = calendar_details.get(str(selected_employee_id)) if selected_employee_id else None
    available_years = list(range(current_year - 1, current_year + 5))
    calendar_period_label = (
        f"{RUSSIAN_MONTH_NAMES[selected_month - 1]} {selected_year}"
        if calendar_view_mode == "month"
        else f"График отпусков на {selected_year} год"
    )

    context.update(
        {
            "current_user": current_user,
            "current_user_final_balance": current_user_final_balance,
            "calendar_view_mode": calendar_view_mode,
            "calendar_period_label": calendar_period_label,
            "calendar_filters": {
                "selected_year": selected_year,
                "selected_month": selected_month,
                "available_years": available_years,
                "available_months": [
                    {"value": index + 1, "label": month_name}
                    for index, month_name in enumerate(RUSSIAN_MONTH_NAMES)
                ],
            },
            "calendar_summary": calendar_summary,
            "calendar_legend": [
                {"status": VacationRequest.STATUS_APPROVED, "label": "Одобрено"},
                {"status": VacationRequest.STATUS_PENDING, "label": "В ожидании"},
                {"status": VacationRequest.STATUS_REJECTED, "label": "Отклонено"},
            ],
            "calendar_rows": calendar_rows,
            "calendar_details": calendar_details,
            "selected_employee_id": selected_employee_id,
            "selected_employee_detail": selected_employee_detail,
            "selected_month_name": RUSSIAN_MONTH_NAMES[selected_month - 1],
            "year_short_headers": RUSSIAN_MONTH_SHORT_NAMES,
            "month_day_headers": [
                {
                    "day": day,
                    "weekday": WEEKDAY_SHORT_NAMES[date(selected_year, selected_month, day).weekday()],
                    "is_weekend": date(selected_year, selected_month, day).weekday() >= 5,
                    "is_today": date(selected_year, selected_month, day) == today,
                }
                for day in range(1, calendar.monthrange(selected_year, selected_month)[1] + 1)
            ],
            "today_iso": today.isoformat(),
        }
    )
    return render(request, "main/calendar.html", context)


@employee_required
def employees(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    current_employee = get_current_employee(request)
    is_manager = is_manager_user(request.user)

    if request.method == "POST" and not is_manager:
        messages.error(request, "У вас нет прав для добавления сотрудников.")
        return redirect("employees")

    if request.method == "POST" and is_manager and "employee_name" in request.POST:
        department = get_object_or_404(Departments, id=request.POST.get("employee_department"))
        new_employee = Employees.objects.create(
            name=request.POST.get("employee_name", "").strip(),
            position=request.POST.get("employee_position", "").strip(),
            date_joined=request.POST.get("employee_date_joined"),
            vacation_days=request.POST.get("employee_vacation_days"),
            department=department,
            password=request.POST.get("employee_password", ""),
            is_manager=request.POST.get("employee_is_manager") == "on",
        )
        sync_employee_user(new_employee, raw_password=request.POST.get("employee_password", ""))
        messages.success(request, "Сотрудник создан.")
        return redirect("employees")

    employees_qs = Employees.objects.select_related("department").order_by("name")
    department_id = "all"
    if is_manager:
        department_id = request.GET.get("department", request.session.get("selected_department", "all"))
        if department_id and department_id != "all":
            employees_qs = employees_qs.filter(department_id=department_id)
    elif current_employee.department_id:
        employees_qs = employees_qs.filter(department=current_employee.department)

    status = request.GET.get("status", "None")
    if status == "True":
        employees_qs = employees_qs.filter(is_working=True)
    elif status == "False":
        employees_qs = employees_qs.filter(is_working=False)

    employees_list = []
    for employee in employees_qs:
        current_balance = employee.vacation_days - employee.used_up_days
        employees_list.append(
            {
                "id": employee.id,
                "name": employee.name,
                "position": employee.position,
                "date_joined": date_format(employee.date_joined, "j E Y", use_l10n=True),
                "vacation_days": current_balance,
                "is_working": employee.is_working,
            }
        )

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"employees": employees_list})

    context.update(
        {
            "employees": employees_list,
            "employees_count": len(employees_list),
            "selected_department": department_id if is_manager else current_employee.department.id if current_employee.department_id else "all",
            "is_manager": is_manager,
        }
    )
    return render(request, "main/employees.html", context)


@employee_required
@manager_required
def departments(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    departments_qs = Departments.objects.all()

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        departments_data = list(departments_qs.values("id", "name", "date_added"))
        return JsonResponse({"departments": departments_data})

    context.update(
        {
            "departments": departments_qs,
            "departments_count": departments_qs.count(),
        }
    )
    return render(request, "main/departments.html", context)


@employee_required
@manager_required
def applications(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    status_filter = request.GET.get("status", "all")
    department_id = request.GET.get("department", "all")
    requests_qs = get_vacation_requests_queryset().order_by("-created_at")

    if status_filter in {
        VacationRequest.STATUS_APPROVED,
        VacationRequest.STATUS_PENDING,
        VacationRequest.STATUS_REJECTED,
    }:
        requests_qs = requests_qs.filter(status=status_filter)

    if department_id != "all":
        try:
            requests_qs = requests_qs.filter(employee__department_id=int(department_id))
        except (TypeError, ValueError):
            department_id = "all"

    vacations = [serialize_vacation_request_row(request_obj) for request_obj in requests_qs]

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        html = "".join(
            f"""
            <tr class="vacation-row" data-id="{vacation.id}">
                <td>{vacation.employee.name}</td>
                <td>{vacation.start_date_formatted}</td>
                <td>{vacation.end_date_formatted}</td>
                <td>{vacation.get_vacation_type_display()}</td>
                <td class="status-cell">
                    <div class="{vacation.status_css_class}">
                        <span class="material-icons-sharp">{vacation.status_icon}</span> {vacation.status_label}
                    </div>
                </td>
            </tr>
            """
            for vacation in vacations
        )
        return JsonResponse({"html": html})

    context.update(
        {
            "vacations": vacations,
            "selected_status": status_filter,
            "selected_department": str(department_id),
        }
    )
    return render(request, "main/applications.html", context)


@employee_required
def vacation_detail(request, pk):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    vacation = get_object_or_404(get_vacation_requests_queryset(), pk=pk)
    enrich_vacation_request(vacation)

    current_employee = get_current_employee(request)
    current_employee_id = current_employee.id if current_employee else None
    is_manager = is_manager_user(request.user)
    if not is_manager and vacation.employee.id != current_employee_id:
        messages.error(request, "У вас нет прав для просмотра чужой заявки.")
        return redirect("main")

    can_delete = vacation.status == VacationRequest.STATUS_PENDING and (
        vacation.employee.id == (current_employee.id if current_employee else None) or is_manager
    )
    current_balance = vacation.employee.vacation_days - vacation.employee.used_up_days

    context.update(
        {
            "vacation": vacation,
            "employee": vacation.employee,
            "status": vacation.status,
            "status_label": vacation.status_label,
            "status_icon": vacation.status_icon,
            "status_css_class": vacation.status_css_class,
            "current_balance": current_balance,
            "is_manager": is_manager,
            "can_delete": can_delete,
        }
    )
    return render(request, "main/vacation_detail.html", context)


@employee_required
@manager_required
def approve_vacation(request, pk):
    vacation = get_object_or_404(VacationRequest, pk=pk, status=VacationRequest.STATUS_PENDING)
    if request.method == "POST":
        vacation.status = VacationRequest.STATUS_APPROVED
        vacation.save(update_fields=["status"])
        sync_employee_vacation_metrics(vacation.employee)
        messages.success(request, "Заявка успешно одобрена.")
    return redirect("applications")


@employee_required
@manager_required
def reject_vacation(request, pk):
    vacation = get_object_or_404(VacationRequest, pk=pk, status=VacationRequest.STATUS_PENDING)
    if request.method == "POST":
        vacation.status = VacationRequest.STATUS_REJECTED
        vacation.save(update_fields=["status"])
        sync_employee_vacation_metrics(vacation.employee)
        messages.error(request, "Заявка отклонена.")
    return redirect("applications")


@employee_required
def delete_vacation(request, pk):
    vacation = get_object_or_404(VacationRequest, pk=pk, status=VacationRequest.STATUS_PENDING)
    current_employee = get_current_employee(request)
    is_manager = is_manager_user(request.user)

    if vacation.employee.id != (current_employee.id if current_employee else None) and not is_manager:
        messages.error(request, "У вас нет прав для удаления этой заявки.")
        return redirect("vacation_detail", pk=pk)

    if request.method == "POST":
        employee = vacation.employee
        vacation.delete()
        sync_employee_vacation_metrics(employee)
        messages.success(request, "Заявка успешно удалена.")
        return redirect("main")

    return redirect("vacation_detail", pk=pk)


@employee_required
@manager_required
def analytics(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    departments = Departments.objects.all()
    total_employees = Employees.objects.count()
    employees_not_on_vacation_count = Employees.objects.filter(is_working=True).count()
    working_employees = round((employees_not_on_vacation_count / total_employees) * 100, 2) if total_employees else 0

    employees_qs = Employees.objects.all()
    total_remaining_days = sum(max(employee.vacation_days - employee.used_up_days, 0) for employee in employees_qs)
    avg_vacation_days = int(total_remaining_days / employees_qs.count()) if employees_qs.exists() else 0

    requests_qs = VacationRequest.objects.all()
    canceled_count = requests_qs.filter(status=VacationRequest.STATUS_REJECTED).count()
    total_applications_count = requests_qs.count()
    rejection_percentage = round((canceled_count / total_applications_count) * 100, 2) if total_applications_count else 0

    approved_requests = requests_qs.filter(status=VacationRequest.STATUS_APPROVED)
    months = {month: 0 for month in range(1, 13)}
    for vacation in approved_requests:
        for month in get_month_range(vacation.start_date, vacation.end_date):
            months[month.month] += 1
    values1 = json.dumps([months[month] for month in range(1, 13)])

    months_duration = {month: timedelta() for month in range(1, 13)}
    months_count = {month: 0 for month in range(1, 13)}
    for vacation in approved_requests:
        duration = max((vacation.end_date - vacation.start_date).days, 0)
        for month in range(vacation.start_date.month, vacation.end_date.month + 1):
            months_duration[month] += timedelta(days=duration)
            months_count[month] += 1
    average_duration = {
        month: (months_duration[month] / months_count[month]).days if months_count[month] else 0
        for month in range(1, 13)
    }
    values2 = json.dumps([average_duration[month] for month in range(1, 13)])

    pending_requests = requests_qs.filter(status=VacationRequest.STATUS_PENDING, start_date__gt=timezone.localdate())
    planned_vacations = {month: 0 for month in range(1, 13)}
    for holiday in pending_requests:
        current_date = holiday.start_date
        while current_date <= holiday.end_date:
            planned_vacations[current_date.month] += 1
            current_date += timedelta(days=1)
    values3 = json.dumps([planned_vacations[month] for month in range(1, 13)])

    context.update(
        {
            "departments": departments,
            "working_employees": working_employees,
            "employees_not_on_vacation_count": employees_not_on_vacation_count,
            "total_employees": total_employees,
            "avg_vacation_days": avg_vacation_days,
            "rejection_percentage": rejection_percentage,
            "canceled_count": canceled_count,
            "total_applications_count": total_applications_count,
            "values1": values1,
            "values2": values2,
            "values3": values3,
        }
    )
    return render(request, "main/analytics.html", context)
