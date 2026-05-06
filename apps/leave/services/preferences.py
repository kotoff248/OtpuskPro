import random
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Notification
from apps.core.services.notifications import mark_notifications_done_by_dedupe_prefix
from apps.employees.models import Employees
from apps.leave.models import VacationPreference, VacationPreferenceCollection

from .constants import LEAVE_ADVANCE_MONTHS
from .dates import add_months_safe
from .notifications import notify_preferences_collection_started


DEMO_FILL_MIN_PERCENT = 72
DEMO_FILL_MAX_PERCENT = 85
DEMO_SKIP_PERCENT = 7


def preference_response_url(year):
    return reverse("vacation_preferences", args=[year])


def preference_notification_dedupe_key(year, employee_id):
    return f"{Notification.TYPE_PREFERENCES_COLLECTION_STARTED}:{year}:{employee_id}"


def preference_notification_dedupe_prefix(year):
    return f"{Notification.TYPE_PREFERENCES_COLLECTION_STARTED}:{year}:"


def get_preference_planning_year(today=None):
    today = today or timezone.localdate()
    return today.year + 1


def get_paid_leave_available_from(employee):
    return add_months_safe(employee.date_joined, LEAVE_ADVANCE_MONTHS)


def employee_can_join_preference_collection(employee, year):
    if employee is None:
        return False
    if not getattr(employee, "is_active_employee", True):
        return False
    if employee.role in Employees.SERVICE_ROLES:
        return False
    year_end = date(year, 12, 31)
    return employee.date_joined <= year_end and get_paid_leave_available_from(employee) <= year_end


def get_eligible_preference_employees(year):
    year_end = date(year, 12, 31)
    candidates = (
        Employees.objects.select_related("department", "employee_position")
        .filter(is_active_employee=True, date_joined__lte=year_end)
        .exclude(role__in=Employees.SERVICE_ROLES)
        .order_by("last_name", "first_name", "middle_name", "id")
    )
    return [employee for employee in candidates if employee_can_join_preference_collection(employee, year)]


def _first_preference(employee, year, priority):
    return (
        VacationPreference.objects.filter(employee=employee, year=year, priority=priority)
        .order_by("created_at", "id")
        .first()
    )


def get_employee_preference_pair(employee, year):
    return {
        VacationPreference.PRIORITY_PRIMARY: _first_preference(employee, year, VacationPreference.PRIORITY_PRIMARY),
        VacationPreference.PRIORITY_BACKUP: _first_preference(employee, year, VacationPreference.PRIORITY_BACKUP),
    }


def get_employee_preference_state(employee, year):
    preferences = list(VacationPreference.objects.filter(employee=employee, year=year))
    if not preferences:
        return "missing"
    if any(preference.status == VacationPreference.STATUS_SKIPPED for preference in preferences):
        return VacationPreference.STATUS_SKIPPED

    pair = get_employee_preference_pair(employee, year)
    primary = pair[VacationPreference.PRIORITY_PRIMARY]
    backup = pair[VacationPreference.PRIORITY_BACKUP]
    if (
        primary is not None
        and backup is not None
        and primary.status == VacationPreference.STATUS_FILLED
        and backup.status == VacationPreference.STATUS_FILLED
    ):
        return VacationPreference.STATUS_FILLED
    return VacationPreference.STATUS_PENDING


def employee_needs_preference_response(employee, year):
    return get_employee_preference_state(employee, year) in {"missing", VacationPreference.STATUS_PENDING}


def ensure_employee_pending_preferences(employee, year):
    if not employee_can_join_preference_collection(employee, year):
        return False
    state = get_employee_preference_state(employee, year)
    if state in {VacationPreference.STATUS_FILLED, VacationPreference.STATUS_SKIPPED}:
        return False

    created = False
    for priority in (VacationPreference.PRIORITY_PRIMARY, VacationPreference.PRIORITY_BACKUP):
        if _first_preference(employee, year, priority) is None:
            VacationPreference.objects.create(
                employee=employee,
                year=year,
                priority=priority,
                status=VacationPreference.STATUS_PENDING,
                created_automatically=True,
            )
            created = True
    return created


def _replace_employee_preferences(employee, year, rows, *, created_automatically):
    VacationPreference.objects.filter(employee=employee, year=year).delete()
    return [
        VacationPreference.objects.create(
            employee=employee,
            year=year,
            priority=row["priority"],
            start_date=row.get("start_date"),
            end_date=row.get("end_date"),
            status=row["status"],
            comment=row.get("comment", ""),
            created_automatically=created_automatically,
        )
        for row in rows
    ]


def mark_preference_notification_done(employee, year):
    now = timezone.now()
    Notification.objects.filter(
        recipient=employee,
        dedupe_key=preference_notification_dedupe_key(year, employee.id),
    ).exclude(status=Notification.STATUS_DONE).update(
        status=Notification.STATUS_DONE,
        read_at=now,
        done_at=now,
        updated_at=now,
    )


def mark_preference_notification_active(employee, year, actor=None):
    notify_preferences_collection_started(year, [employee], actor=actor)


def _mark_answered_preference_notifications_done(employees, year):
    for employee in employees:
        if get_employee_preference_state(employee, year) in {
            VacationPreference.STATUS_FILLED,
            VacationPreference.STATUS_SKIPPED,
        }:
            mark_preference_notification_done(employee, year)


@transaction.atomic
def submit_employee_preferences(
    *,
    collection,
    employee,
    primary_start=None,
    primary_end=None,
    backup_start=None,
    backup_end=None,
    comment="",
    no_preferences=False,
):
    today = timezone.localdate()
    if (
        collection.status != VacationPreferenceCollection.STATUS_OPEN
        or today > collection.deadline
        or collection.year != get_preference_planning_year(today)
    ):
        raise ValidationError("Сбор пожеланий закрыт, изменить ответ уже нельзя.")

    if no_preferences:
        rows = [
            {
                "priority": VacationPreference.PRIORITY_PRIMARY,
                "status": VacationPreference.STATUS_SKIPPED,
                "comment": comment,
            },
            {
                "priority": VacationPreference.PRIORITY_BACKUP,
                "status": VacationPreference.STATUS_SKIPPED,
                "comment": comment,
            },
        ]
    else:
        rows = [
            {
                "priority": VacationPreference.PRIORITY_PRIMARY,
                "start_date": primary_start,
                "end_date": primary_end,
                "status": VacationPreference.STATUS_FILLED,
                "comment": comment,
            },
            {
                "priority": VacationPreference.PRIORITY_BACKUP,
                "start_date": backup_start,
                "end_date": backup_end,
                "status": VacationPreference.STATUS_FILLED,
                "comment": comment,
            },
        ]
    preferences = _replace_employee_preferences(
        employee,
        collection.year,
        rows,
        created_automatically=False,
    )
    mark_preference_notification_done(employee, collection.year)
    return preferences


def _dates_overlap(left_start, left_end, right_start, right_end):
    return left_start <= right_end and right_start <= left_end


def _random_period(year, earliest_start, duration, rng, excluded_periods=None):
    excluded_periods = excluded_periods or []
    year_end = date(year, 12, 31)
    duration = max(1, min(duration, (year_end - earliest_start).days + 1))
    latest_start = year_end - timedelta(days=duration - 1)
    month_pool = [2, 3, 4, 6, 7, 8, 9, 10, 11]

    for _ in range(40):
        month = rng.choice(month_pool)
        day = rng.randint(1, 12)
        candidate_start = max(date(year, month, min(day, 28)), earliest_start)
        if candidate_start > latest_start:
            continue
        candidate_end = candidate_start + timedelta(days=duration - 1)
        if any(_dates_overlap(candidate_start, candidate_end, start, end) for start, end in excluded_periods):
            continue
        return candidate_start, candidate_end

    fallback_start = earliest_start
    for start, end in excluded_periods:
        fallback_start = max(fallback_start, end + timedelta(days=7))
    if fallback_start > latest_start:
        fallback_start = earliest_start
    return fallback_start, fallback_start + timedelta(days=duration - 1)


def _demo_comment(rng):
    comments = [
        "Хочется совместить отпуск с семейной поездкой.",
        "Желательно поставить отпуск на спокойный период отдела.",
        "Готов рассмотреть перенос, если будет высокая нагрузка.",
        "Основной вариант связан с личными планами.",
        "Запасной период подойдёт, если летние даты будут заняты.",
        "Важно не ставить отпуск на период квартальной отчётности.",
    ]
    return rng.choice(comments)


def _build_demo_preference_rows(employee, year, rng):
    earliest_start = max(date(year, 1, 1), get_paid_leave_available_from(employee))
    year_end = date(year, 12, 31)
    if earliest_start > year_end:
        return []

    primary_duration = rng.choice([14, 21, 28])
    backup_duration = rng.choice([14, 21])
    primary_start, primary_end = _random_period(year, earliest_start, primary_duration, rng)
    backup_start, backup_end = _random_period(
        year,
        earliest_start,
        backup_duration,
        rng,
        excluded_periods=[(primary_start, primary_end)],
    )
    comment = _demo_comment(rng)
    return [
        {
            "priority": VacationPreference.PRIORITY_PRIMARY,
            "start_date": primary_start,
            "end_date": primary_end,
            "status": VacationPreference.STATUS_FILLED,
            "comment": comment,
        },
        {
            "priority": VacationPreference.PRIORITY_BACKUP,
            "start_date": backup_start,
            "end_date": backup_end,
            "status": VacationPreference.STATUS_FILLED,
            "comment": comment,
        },
    ]


def _demo_fill_preferences(collection, employees):
    pending_employees = [
        employee
        for employee in employees
        if get_employee_preference_state(employee, collection.year) == VacationPreference.STATUS_PENDING
    ]
    if not pending_employees:
        return {"filled": 0, "skipped": 0}

    mandatory_pending = next((employee for employee in pending_employees if employee.login == "employ_1"), None)
    if mandatory_pending is not None:
        pending_employees = [employee for employee in pending_employees if employee.id != mandatory_pending.id]

    rng = random.Random(timezone.now().timestamp())
    rng.shuffle(pending_employees)
    fill_percent = rng.randint(DEMO_FILL_MIN_PERCENT, DEMO_FILL_MAX_PERCENT)
    fill_count = max(1, round(len(pending_employees) * fill_percent / 100))
    skipped_count = round(len(pending_employees) * DEMO_SKIP_PERCENT / 100)
    filled_employees = pending_employees[:fill_count]
    skipped_employees = pending_employees[fill_count : fill_count + skipped_count]

    filled = 0
    for employee in filled_employees:
        rows = _build_demo_preference_rows(employee, collection.year, rng)
        if rows:
            _replace_employee_preferences(employee, collection.year, rows, created_automatically=True)
            filled += 1

    skipped = 0
    for employee in skipped_employees:
        _replace_employee_preferences(
            employee,
            collection.year,
            [
                {
                    "priority": VacationPreference.PRIORITY_PRIMARY,
                    "status": VacationPreference.STATUS_SKIPPED,
                    "comment": "Пожелания не указаны.",
                },
                {
                    "priority": VacationPreference.PRIORITY_BACKUP,
                    "status": VacationPreference.STATUS_SKIPPED,
                    "comment": "Пожелания не указаны.",
                },
            ],
            created_automatically=True,
        )
        skipped += 1
    return {"filled": filled, "skipped": skipped}


@transaction.atomic
def start_preference_collection(*, year, deadline, actor, demo_autofill=False):
    now = timezone.now()
    collection, created = VacationPreferenceCollection.objects.select_for_update().get_or_create(
        year=year,
        defaults={
            "deadline": deadline,
            "status": VacationPreferenceCollection.STATUS_OPEN,
            "started_by": actor,
            "started_at": now,
            "demo_autofill_enabled": demo_autofill,
        },
    )
    if not created:
        collection.status = VacationPreferenceCollection.STATUS_OPEN
        collection.deadline = deadline
        collection.started_by = actor
        collection.started_at = now
        collection.finished_by = None
        collection.finished_at = None
        collection.demo_autofill_enabled = demo_autofill
        collection.save(
            update_fields=[
                "status",
                "deadline",
                "started_by",
                "started_at",
                "finished_by",
                "finished_at",
                "demo_autofill_enabled",
            ]
        )

    VacationPreference.objects.filter(year=year).delete()

    eligible_employees = get_eligible_preference_employees(year)
    for employee in eligible_employees:
        ensure_employee_pending_preferences(employee, year)

    demo_stats = {"filled": 0, "skipped": 0}
    if demo_autofill:
        demo_stats = _demo_fill_preferences(collection, eligible_employees)

    notify_preferences_collection_started(year, eligible_employees, actor=actor)
    _mark_answered_preference_notifications_done(eligible_employees, year)

    pending_count = sum(
        1
        for employee in eligible_employees
        if get_employee_preference_state(employee, year) == VacationPreference.STATUS_PENDING
    )
    return {
        "collection": collection,
        "eligible_count": len(eligible_employees),
        "notified_count": pending_count,
        "demo_filled_count": demo_stats["filled"],
        "demo_skipped_count": demo_stats["skipped"],
    }


@transaction.atomic
def finish_preference_collection(*, year, actor):
    collection = VacationPreferenceCollection.objects.select_for_update().get(year=year)
    collection.status = VacationPreferenceCollection.STATUS_FINISHED
    collection.finished_by = actor
    collection.finished_at = timezone.now()
    collection.save(update_fields=["status", "finished_by", "finished_at"])
    mark_notifications_done_by_dedupe_prefix(preference_notification_dedupe_prefix(year))
    return collection


def attach_employee_to_open_preference_collections(employee, *, actor=None):
    attached_years = []
    if employee.role in Employees.SERVICE_ROLES or not employee.is_active_employee:
        return attached_years

    collections = VacationPreferenceCollection.objects.filter(status=VacationPreferenceCollection.STATUS_OPEN)
    for collection in collections:
        if timezone.localdate() > collection.deadline:
            continue
        if not employee_can_join_preference_collection(employee, collection.year):
            continue
        ensure_employee_pending_preferences(employee, collection.year)
        if employee_needs_preference_response(employee, collection.year):
            mark_preference_notification_active(employee, collection.year, actor=actor)
            attached_years.append(collection.year)
    return attached_years


def build_preference_collection_summary(year):
    eligible_employees = get_eligible_preference_employees(year)
    total = len(eligible_employees)
    counts = {
        VacationPreference.STATUS_FILLED: 0,
        VacationPreference.STATUS_SKIPPED: 0,
        VacationPreference.STATUS_PENDING: 0,
        "missing": 0,
    }
    for employee in eligible_employees:
        counts[get_employee_preference_state(employee, year)] += 1

    ready = counts[VacationPreference.STATUS_FILLED] + counts[VacationPreference.STATUS_SKIPPED]
    attention = counts[VacationPreference.STATUS_PENDING] + counts["missing"]
    ready_percentage = round(ready * 100 / total) if total else 0
    return {
        "total": total,
        "ready": ready,
        "pending": counts[VacationPreference.STATUS_PENDING],
        "skipped": counts[VacationPreference.STATUS_SKIPPED],
        "missing": counts["missing"],
        "attention": attention,
        "ready_percentage": ready_percentage,
    }


def build_calendar_preference_collection_context(current_employee, calendar_year):
    today = timezone.localdate()
    year = get_preference_planning_year(today)
    collection = VacationPreferenceCollection.objects.filter(year=year).first()
    summary = build_preference_collection_summary(year)
    is_open = collection is not None and collection.status == VacationPreferenceCollection.STATUS_OPEN
    is_finished = collection is not None and collection.status == VacationPreferenceCollection.STATUS_FINISHED
    deadline_passed = is_open and today > collection.deadline
    return {
        "collection": collection,
        "can_manage": current_employee is not None and current_employee.role == Employees.ROLE_HR,
        "year": year,
        "is_open": is_open,
        "is_finished": is_finished,
        "deadline_passed": deadline_passed,
        "status_label": collection.get_status_display() if collection else "Не начат",
        "deadline": collection.deadline if collection else None,
        "default_deadline": today + timedelta(days=14),
        "start_url": reverse("preferences_collection_start"),
        "finish_url": reverse("preferences_collection_finish", args=[year]),
        "response_url": preference_response_url(year),
        "summary": summary,
    }


def get_employee_preference_page_context(employee, collection):
    pair = get_employee_preference_pair(employee, collection.year)
    state = get_employee_preference_state(employee, collection.year)
    today = timezone.localdate()
    planning_year = get_preference_planning_year(today)
    paid_leave_available_from = get_paid_leave_available_from(employee)
    editable = (
        collection.status == VacationPreferenceCollection.STATUS_OPEN
        and today <= collection.deadline
        and collection.year == planning_year
    )
    return {
        "collection": collection,
        "preference_state": state,
        "primary_preference": pair[VacationPreference.PRIORITY_PRIMARY],
        "backup_preference": pair[VacationPreference.PRIORITY_BACKUP],
        "editable": editable,
        "planning_year": planning_year,
        "is_planning_year": collection.year == planning_year,
        "paid_leave_available_from": paid_leave_available_from,
        "show_paid_leave_available_hint": today < paid_leave_available_from,
    }
