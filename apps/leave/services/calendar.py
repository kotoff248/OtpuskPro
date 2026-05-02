import calendar
from collections import defaultdict
from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone

from apps.employees.models import Employees
from apps.leave.models import DepartmentWorkload, VacationRequest, VacationScheduleItem

from .constants import (
    CALENDAR_VISIBLE_STATUSES,
    DISPLAY_FREE,
    DISPLAY_MIXED,
    DISPLAY_REQUEST_APPROVED,
    DISPLAY_REQUEST_PENDING,
    DISPLAY_REQUEST_REJECTED,
    DISPLAY_SCHEDULE_APPROVED,
    DISPLAY_SCHEDULE_CANCELLED,
    DISPLAY_SCHEDULE_PLANNED,
    DISPLAY_SCHEDULE_TRANSFERRED,
    DISPLAY_STATUS_PRIORITY,
    DISPLAY_STATUS_UI,
    REQUEST_STATUS_TO_DISPLAY_STATUS,
    REQUEST_STATUS_UI,
    RUSSIAN_MONTH_NAMES,
    RUSSIAN_MONTH_SHORT_NAMES,
    SCHEDULE_STATUS_TO_CALENDAR_STATUS,
    SCHEDULE_STATUS_TO_DISPLAY_STATUS,
    VACATION_STATUS_META,
)
from .dates import clip_period_to_range, format_period_label, get_month_end, get_requested_days, iterate_dates
from .employee_presentation import get_employee_identity_presentation
from .querysets import exclude_converted_paid_requests, get_vacation_requests_queryset
from .staffing import (
    build_department_staffing_context,
    evaluate_department_staffing_state,
    evaluate_enterprise_leadership_state,
    format_staff_count,
    get_department_staffing_rule,
    get_staffing_limits_for_date,
)

RUSSIAN_MONTH_GENITIVE_NAMES = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

def get_calendar_redirect_url(request):
    next_view = request.POST.get("next_view_mode", request.GET.get("view", "month"))
    next_year = request.POST.get("next_year", request.GET.get("year", timezone.localdate().year))
    next_month = request.POST.get("next_month", request.GET.get("month", timezone.localdate().month))
    return f"{request.path}?view={next_view}&year={next_year}&month={next_month}"

def _schedule_item_source_label(item):
    if item.status == VacationScheduleItem.STATUS_TRANSFERRED:
        return "Перенос"
    if item.source == VacationScheduleItem.SOURCE_MANUAL:
        return "Дополнение к графику"
    if item.source == VacationScheduleItem.SOURCE_TRANSFER:
        return "Перенос"
    return "Годовой график"

def _entry_overlaps_period(entry, period_start, period_end):
    return clip_period_to_range(entry["start_date"], entry["end_date"], period_start, period_end) is not None

def _is_conflict_relevant_entry(entry):
    if entry.get("source_kind") == "request":
        return entry.get("status") in VacationRequest.ACTIVE_STATUSES
    if entry.get("source_kind") == "schedule":
        return entry.get("schedule_status") in VacationScheduleItem.ACTIVE_STATUSES
    return False

def _format_conflict_reason(current_date, absent_count, max_absent, remaining_staff_count, min_staff_required):
    reason_parts = []
    if max_absent and absent_count > max_absent:
        reason_parts.append(f"отсутствуют {absent_count}, лимит {max_absent}")
    if min_staff_required and remaining_staff_count < min_staff_required:
        reason_parts.append(f"останется {remaining_staff_count}, минимум {min_staff_required}")
    return f'{current_date.strftime("%d.%m.%Y")}: {"; ".join(reason_parts)}'

def _format_group_conflict_reason(current_date, group_name, available_count, min_staff_required, absent_count, max_absent):
    reason_parts = []
    if min_staff_required and available_count < min_staff_required:
        reason_parts.append(f"не хватает: {group_name} ({available_count}/{min_staff_required})")
    if max_absent is not None and absent_count > max_absent:
        reason_parts.append(f"{group_name}: отсутствуют {absent_count}, лимит {max_absent}")
    return f'{current_date.strftime("%d.%m.%Y")}: {"; ".join(reason_parts)}'

def _format_substitution_risk_reason(current_date, group_name, covered_count):
    return f'{current_date.strftime("%d.%m.%Y")}: {group_name} закрыта замещением ({covered_count})'


def _format_staffing_issue_reason(current_date, issue):
    issue_kind = issue.get("kind")
    if issue_kind == "substitution_used":
        return _format_substitution_risk_reason(
            current_date,
            issue.get("affected_group", ""),
            issue.get("covered_staff", 0),
        )
    if issue_kind in {"group_shortage", "group_absence_limit"}:
        return _format_group_conflict_reason(
            current_date,
            issue.get("affected_group", ""),
            issue.get("remaining_staff", 0),
            issue.get("required_staff", 0),
            issue.get("absent_staff", 0),
            issue.get("max_absent", 0),
        )
    if issue_kind == "department_leadership_pair":
        return f'{current_date.strftime("%d.%m.%Y")}: руководитель отдела и заместитель отсутствуют'
    if issue_kind == "enterprise_leadership_pair":
        return f'{current_date.strftime("%d.%m.%Y")}: руководитель предприятия и заместитель отсутствуют'
    return _format_conflict_reason(
        current_date,
        issue.get("absent_staff", 0),
        issue.get("max_absent", 0),
        issue.get("remaining_staff", 0),
        issue.get("required_staff", 0),
    )


def _build_staffing_issue_event(current_date, issue, fallback_employee_ids):
    affected_employee_ids = issue.get("affected_employee_ids") or fallback_employee_ids
    return {
        "date": current_date,
        "kind": issue.get("kind", ""),
        "severity": issue.get("severity", ""),
        "title": issue.get("title", ""),
        "text": issue.get("text", ""),
        "affected_department": issue.get("affected_department", ""),
        "affected_group": issue.get("affected_group", ""),
        "affected_employee_ids": tuple(sorted(affected_employee_ids or [])),
        "remaining_staff": issue.get("remaining_staff"),
        "required_staff": issue.get("required_staff"),
        "missing_staff": issue.get("missing_staff"),
        "absent_staff": issue.get("absent_staff"),
        "max_absent": issue.get("max_absent"),
        "covered_staff": issue.get("covered_staff"),
        "substitute_groups": issue.get("substitute_groups", ""),
    }


def _staffing_issue_event_key(event):
    return (
        event.get("kind", ""),
        event.get("severity", ""),
        event.get("affected_department", ""),
        event.get("affected_group", ""),
        event.get("remaining_staff"),
        event.get("required_staff"),
        event.get("missing_staff"),
        event.get("absent_staff"),
        event.get("max_absent"),
        event.get("covered_staff"),
        event.get("substitute_groups", ""),
        tuple(event.get("affected_employee_ids", ())),
    )


def _append_staffing_issue_event(meta, employee_ids, event):
    event_key = (_staffing_issue_event_key(event), event["date"])
    for employee_id in employee_ids:
        meta[employee_id]["dates"].add(event["date"].isoformat())
        if event_key in meta[employee_id]["event_keys"]:
            continue
        meta[employee_id]["event_keys"].add(event_key)
        meta[employee_id]["events"].append(event)


def _get_staffing_issue_meta(employees, employee_entries, period_start, period_end):
    department_by_id = {employee.department_id: employee.department for employee in employees if employee.department_id}
    if not department_by_id:
        return {"conflicts": {}, "substitution_risks": {}}

    department_ids = set(department_by_id)
    staffing_rules = {
        department_id: get_department_staffing_rule(department)
        for department_id, department in department_by_id.items()
    }
    workloads = DepartmentWorkload.objects.filter(
        department_id__in=department_ids,
        year__gte=period_start.year,
        year__lte=period_end.year,
    )
    workload_by_department_month = {
        (workload.department_id, workload.year, workload.month): workload
        for workload in workloads
    }
    staffing_contexts = {
        department_id: build_department_staffing_context(department, period_end)
        for department_id, department in department_by_id.items()
    }

    absent_by_department_day = defaultdict(set)
    absent_by_day = defaultdict(set)
    for entries in employee_entries.values():
        for entry in entries:
            if not _is_conflict_relevant_entry(entry):
                continue

            clipped_period = clip_period_to_range(entry["start_date"], entry["end_date"], period_start, period_end)
            if clipped_period is None:
                continue

            clipped_start, clipped_end = clipped_period
            department_id = entry.get("department_id")
            for current_date in iterate_dates(clipped_start, clipped_end):
                absent_by_day[current_date].add(entry["employee_id"])
                if department_id in department_ids:
                    absent_by_department_day[(department_id, current_date)].add(entry["employee_id"])

    conflict_meta = defaultdict(lambda: {"summaries": [], "dates": set(), "events": [], "event_keys": set()})
    substitution_risk_meta = defaultdict(lambda: {"summaries": [], "dates": set(), "events": [], "event_keys": set()})

    def add_conflict(employee_ids, current_date, reason, event):
        for employee_id in employee_ids:
            if reason not in conflict_meta[employee_id]["summaries"]:
                conflict_meta[employee_id]["summaries"].append(reason)
        _append_staffing_issue_event(conflict_meta, employee_ids, event)

    def add_substitution_risk(employee_ids, current_date, reason, event):
        for employee_id in employee_ids:
            if reason not in substitution_risk_meta[employee_id]["summaries"]:
                substitution_risk_meta[employee_id]["summaries"].append(reason)
        _append_staffing_issue_event(substitution_risk_meta, employee_ids, event)

    for (department_id, current_date), absent_employee_ids in absent_by_department_day.items():
        department = department_by_id[department_id]
        min_staff_required, max_absent = get_staffing_limits_for_date(
            department,
            current_date,
            workload_by_department_month,
            staffing_rules,
        )
        staffing_evaluation = evaluate_department_staffing_state(
            staffing_contexts[department_id],
            absent_employee_ids,
            min_staff_required=min_staff_required,
            max_absent=max_absent,
            include_limit_warnings=False,
        )
        for issue in staffing_evaluation["issues"]:
            affected_employee_ids = issue.get("affected_employee_ids") or absent_employee_ids
            reason = _format_staffing_issue_reason(current_date, issue)
            event = _build_staffing_issue_event(current_date, issue, absent_employee_ids)
            if issue.get("kind") == "substitution_used":
                add_substitution_risk(affected_employee_ids, current_date, reason, event)
            elif issue.get("severity") == "conflict":
                add_conflict(affected_employee_ids, current_date, reason, event)

    for current_date, absent_employee_ids in absent_by_day.items():
        enterprise_evaluation = evaluate_enterprise_leadership_state(absent_employee_ids, period_end)
        for issue in enterprise_evaluation["issues"]:
            affected_employee_ids = issue.get("affected_employee_ids") or absent_employee_ids
            add_conflict(
                affected_employee_ids,
                current_date,
                _format_staffing_issue_reason(current_date, issue),
                _build_staffing_issue_event(current_date, issue, absent_employee_ids),
            )

    return {
        "conflicts": {
            employee_id: {
                "dates": meta["dates"],
                "summary": "; ".join(meta["summaries"][:2]),
                "events": meta["events"],
            }
            for employee_id, meta in conflict_meta.items()
        },
        "substitution_risks": {
            employee_id: {
                "dates": meta["dates"],
                "summary": "; ".join(meta["summaries"][:2]),
                "events": meta["events"],
            }
            for employee_id, meta in substitution_risk_meta.items()
        },
    }

def _get_conflict_meta(employees, employee_entries, period_start, period_end):
    return _get_staffing_issue_meta(employees, employee_entries, period_start, period_end)["conflicts"]

def _get_conflicting_employee_ids(employees, employee_entries, period_start, period_end):
    return set(_get_conflict_meta(employees, employee_entries, period_start, period_end))

def _risk_label_for_level(risk_level):
    return dict(VacationRequest.RISK_CHOICES).get(risk_level, "Низкий")

def _build_entry_anchor(entry):
    return {
        "employee_id": entry["employee_id"],
        "source_kind": entry.get("source_kind", ""),
        "source_id": entry.get("source_id"),
        "start_date": entry["start_date"].isoformat(),
        "end_date": entry["end_date"].isoformat(),
    }

def _shorten_conflict_summary(summary):
    if not summary:
        return ""

    first_reason = summary.split("; ", 1)[0].strip()
    if ": " in first_reason:
        first_reason = first_reason.split(": ", 1)[1].strip()

    if len(first_reason) <= 34:
        return first_reason

    return first_reason[:31].rstrip() + "..."

def _build_row_issue_chips(employee_issue_meta, issue_filter):
    chips = []
    if employee_issue_meta["has_high_risk"]:
        chips.append(
            {
                "kind": "risk",
                "label": employee_issue_meta["risk_summary"] if issue_filter == "risk" else "Высокий риск",
                "icon": "bolt",
                "icon_type": "material",
            }
        )
    if employee_issue_meta["has_conflict"]:
        conflict_label = "Конфликт"
        if issue_filter == "conflict":
            conflict_reason = _shorten_conflict_summary(employee_issue_meta["conflict_summary"])
            conflict_label = f"Конфликт: {conflict_reason}" if conflict_reason else "Конфликт"
        chips.append({"kind": "conflict", "label": conflict_label, "icon": "⚔", "icon_type": "symbol"})
    return chips

def _entry_identity(entry):
    return (entry.get("source_kind", ""), entry.get("source_id"), entry["start_date"], entry["end_date"])

def _starts_with_issue_date(value):
    return (
        len(value) >= 11
        and value[2] == "."
        and value[5] == "."
        and value[10] == ":"
        and value[:2].isdigit()
        and value[3:5].isdigit()
        and value[6:10].isdigit()
    )

def _split_issue_summary(summary):
    summary = (summary or "").strip()
    if not summary:
        return []

    reasons = []
    for fragment in (part.strip() for part in summary.split("; ") if part.strip()):
        if _starts_with_issue_date(fragment) or not reasons:
            reasons.append(fragment)
        else:
            reasons[-1] = f"{reasons[-1]}; {fragment}"
    return reasons

def _split_issue_date(reason):
    if _starts_with_issue_date(reason):
        return reason[:10], reason[12:].strip()
    return "", reason

def _format_problem_period_label(start_date, end_date):
    if start_date == end_date:
        return f"{start_date.day} {RUSSIAN_MONTH_GENITIVE_NAMES[start_date.month - 1]}"
    if start_date.month == end_date.month and start_date.year == end_date.year:
        return f"{start_date.day}-{end_date.day} {RUSSIAN_MONTH_GENITIVE_NAMES[start_date.month - 1]}"
    return (
        f"{start_date.day} {RUSSIAN_MONTH_GENITIVE_NAMES[start_date.month - 1]} - "
        f"{end_date.day} {RUSSIAN_MONTH_GENITIVE_NAMES[end_date.month - 1]}"
    )

def _short_employee_name(full_name):
    parts = str(full_name or "").split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[1]}"
    return str(full_name or "").strip()

def _build_affected_names(employee_ids, employee_names_by_id, limit=4):
    names = sorted(
        _short_employee_name(employee_names_by_id.get(employee_id, ""))
        for employee_id in employee_ids
        if employee_names_by_id.get(employee_id)
    )
    visible_names = names[:limit]
    return visible_names, max(len(names) - len(visible_names), 0)

def _group_staffing_issue_events(events):
    buckets = defaultdict(list)
    seen = set()
    for event in events or []:
        event_key = (_staffing_issue_event_key(event), event.get("date"))
        if event_key in seen:
            continue
        seen.add(event_key)
        buckets[_staffing_issue_event_key(event)].append(event)

    groups = []
    for key, bucket_events in buckets.items():
        bucket_events.sort(key=lambda item: item["date"])
        current_group = None
        for event in bucket_events:
            if current_group and event["date"] == current_group["end_date"] + timedelta(days=1):
                current_group["end_date"] = event["date"]
                current_group["dates"].append(event["date"])
                continue

            if current_group:
                groups.append(current_group)
            current_group = {
                "key": key,
                "event": event,
                "start_date": event["date"],
                "end_date": event["date"],
                "dates": [event["date"]],
            }
        if current_group:
            groups.append(current_group)

    return sorted(groups, key=lambda item: (item["start_date"], item["event"].get("kind", "")))

def _build_group_staffing_combined_event(absence_event, shortage_event):
    missing_staff = shortage_event.get("missing_staff")
    if missing_staff is None:
        missing_staff = max(
            int(shortage_event.get("required_staff") or 0) - int(shortage_event.get("remaining_staff") or 0),
            0,
        )

    affected_employee_ids = tuple(
        sorted(set(absence_event.get("affected_employee_ids", ())) & set(shortage_event.get("affected_employee_ids", ())))
    )
    return {
        "date": absence_event["date"],
        "kind": "group_staffing_combined",
        "severity": "conflict",
        "title": "Группа не проходит по составу",
        "text": "",
        "affected_department": absence_event.get("affected_department") or shortage_event.get("affected_department", ""),
        "affected_group": absence_event.get("affected_group") or shortage_event.get("affected_group", ""),
        "affected_employee_ids": affected_employee_ids,
        "remaining_staff": shortage_event.get("remaining_staff"),
        "required_staff": shortage_event.get("required_staff"),
        "missing_staff": missing_staff,
        "absent_staff": absence_event.get("absent_staff"),
        "max_absent": absence_event.get("max_absent"),
        "covered_staff": shortage_event.get("covered_staff") or absence_event.get("covered_staff"),
        "substitute_groups": shortage_event.get("substitute_groups", "") or absence_event.get("substitute_groups", ""),
    }

def _combine_group_staffing_events(events):
    events = list(events or [])
    grouped_events = defaultdict(list)
    passthrough_indexes = set()

    for index, event in enumerate(events):
        if event.get("kind") not in {"group_absence_limit", "group_shortage"}:
            passthrough_indexes.add(index)
            continue
        if not event.get("affected_group"):
            passthrough_indexes.add(index)
            continue

        grouped_events[
            (
                event.get("date"),
                event.get("affected_group"),
                tuple(event.get("affected_employee_ids", ())),
            )
        ].append((index, event))

    combined_indexes = set()
    combined_items = []
    for indexed_events in grouped_events.values():
        absence_items = [
            (index, event)
            for index, event in indexed_events
            if event.get("kind") == "group_absence_limit"
        ]
        shortage_items = [
            (index, event)
            for index, event in indexed_events
            if event.get("kind") == "group_shortage"
        ]
        if not absence_items or not shortage_items:
            continue

        for (absence_index, absence_event), (shortage_index, shortage_event) in zip(absence_items, shortage_items):
            combined_indexes.update({absence_index, shortage_index})
            combined_items.append(
                (
                    min(absence_index, shortage_index),
                    _build_group_staffing_combined_event(absence_event, shortage_event),
                )
            )

    merged_items = [
        (index, event)
        for index, event in enumerate(events)
        if index in passthrough_indexes or index not in combined_indexes
    ]
    merged_items.extend(combined_items)
    return [event for _, event in sorted(merged_items, key=lambda item: item[0])]

def _problem_title_for_event(event):
    issue_kind = event.get("kind")
    if issue_kind == "group_staffing_combined":
        return "Группа не проходит по составу"
    if issue_kind in {"group_absence_limit", "department_absence_limit"}:
        return "Превышен лимит отсутствующих"
    if issue_kind == "group_shortage":
        return "Группа ниже минимума"
    if issue_kind == "department_staff_shortage":
        return "Отдел ниже минимума"
    if issue_kind == "substitution_used":
        return "Нужно замещение"
    if issue_kind == "department_leadership_pair":
        return "Нет пары управления отделом"
    if issue_kind == "enterprise_leadership_pair":
        return "Нет пары управления предприятием"
    if issue_kind == "stored_high_risk":
        return "Высокий риск записи"
    return event.get("title") or "Риск состава"

def _event_scope_label(event):
    return event.get("affected_group") or event.get("affected_department") or "Состав"

def _problem_text_for_event(event):
    issue_kind = event.get("kind")
    scope = _event_scope_label(event)
    if issue_kind == "group_staffing_combined":
        return (
            f"{scope}: отсутствуют {format_staff_count(event.get('absent_staff', 0))}, "
            f"останется {format_staff_count(event.get('remaining_staff', 0))} "
            f"при минимуме {format_staff_count(event.get('required_staff', 0))}"
        )
    if issue_kind in {"group_absence_limit", "department_absence_limit"}:
        return (
            f"{scope}: отсутствуют {format_staff_count(event.get('absent_staff', 0))} "
            f"при лимите {format_staff_count(event.get('max_absent', 0))}"
        )
    if issue_kind in {"group_shortage", "department_staff_shortage"}:
        return (
            f"{scope}: останется {format_staff_count(event.get('remaining_staff', 0))} "
            f"при минимуме {format_staff_count(event.get('required_staff', 0))}"
        )
    if issue_kind == "substitution_used":
        return f"{scope}: дефицит закрывается замещением"
    return event.get("text") or "Есть риск для состава в выбранном периоде."

def _impact_label_for_event(event):
    issue_kind = event.get("kind")
    if issue_kind == "group_staffing_combined":
        missing = event.get("missing_staff")
        if missing is None:
            missing = max(int(event.get("required_staff") or 0) - int(event.get("remaining_staff") or 0), 0)
        if missing:
            return f"Не хватает: {format_staff_count(missing)}"
        excess = max(int(event.get("absent_staff") or 0) - int(event.get("max_absent") or 0), 0)
        return f"Превышение: {format_staff_count(excess)}" if excess else ""
    if issue_kind in {"group_absence_limit", "department_absence_limit"}:
        excess = max(int(event.get("absent_staff") or 0) - int(event.get("max_absent") or 0), 0)
        return f"Превышение: {format_staff_count(excess)}" if excess else ""
    if issue_kind in {"group_shortage", "department_staff_shortage"}:
        missing = event.get("missing_staff")
        if missing is None:
            missing = max(int(event.get("required_staff") or 0) - int(event.get("remaining_staff") or 0), 0)
        return f"Не хватает: {format_staff_count(missing)}" if missing else ""
    if issue_kind == "substitution_used":
        covered = int(event.get("covered_staff") or 0)
        return f"Замещение покрывает {format_staff_count(covered)}" if covered else ""
    return ""

def _group_dates_overlap(left_group, right_group):
    return bool(set(left_group["dates"]) & set(right_group["dates"]))

def _groups_share_scope(left_group, right_group):
    left_event = left_group["event"]
    right_event = right_group["event"]
    return (
        left_event.get("affected_group")
        and left_event.get("affected_group") == right_event.get("affected_group")
    )

def _substitution_label_for_problem(event, substitution_groups):
    if not substitution_groups:
        return ""

    covered_staff = max(int(group["event"].get("covered_staff") or 0) for group in substitution_groups)
    substitute_labels = sorted(
        {
            group["event"].get("substitute_groups", "")
            for group in substitution_groups
            if group["event"].get("substitute_groups")
        }
    )
    label = f"Замещение покрывает {format_staff_count(covered_staff)}"
    if substitute_labels:
        label = f"{label}: {'; '.join(substitute_labels)}"

    issue_kind = event.get("kind")
    if issue_kind == "group_staffing_combined":
        missing = event.get("missing_staff")
        if missing is None:
            missing = max(int(event.get("required_staff") or 0) - int(event.get("remaining_staff") or 0), 0)
        if missing:
            return f"{label}, но всё равно не хватает {format_staff_count(missing)}."
        excess = max(int(event.get("absent_staff") or 0) - int(event.get("max_absent") or 0), 0)
        if excess:
            return f"{label}, но лимит всё равно превышен на {format_staff_count(excess)}."
    if issue_kind in {"group_absence_limit", "department_absence_limit"}:
        excess = max(int(event.get("absent_staff") or 0) - int(event.get("max_absent") or 0), 0)
        if excess:
            return f"{label}, но лимит всё равно превышен на {format_staff_count(excess)}."
    if issue_kind in {"group_shortage", "department_staff_shortage"}:
        missing = event.get("missing_staff")
        if missing is None:
            missing = max(int(event.get("required_staff") or 0) - int(event.get("remaining_staff") or 0), 0)
        if missing:
            return f"{label}, но всё равно не хватает {format_staff_count(missing)}."
    return f"{label}."

def _build_problem_from_group(group, employee_names_by_id, substitution_groups=None):
    event = group["event"]
    affected_names, extra_affected_count = _build_affected_names(
        event.get("affected_employee_ids", ()),
        employee_names_by_id,
    )
    return {
        "kind": event.get("kind", ""),
        "severity": event.get("severity", ""),
        "period_label": _format_problem_period_label(group["start_date"], group["end_date"]),
        "title": _problem_title_for_event(event),
        "text": _problem_text_for_event(event),
        "impact_label": _impact_label_for_event(event),
        "affected_names": affected_names,
        "extra_affected_count": extra_affected_count,
        "substitution_label": _substitution_label_for_problem(event, substitution_groups or []),
    }

def _build_fallback_risk_problem(summary, employee_id, employee_names_by_id):
    affected_names, extra_affected_count = _build_affected_names([employee_id], employee_names_by_id)
    return {
        "kind": "stored_high_risk",
        "severity": "high",
        "period_label": "",
        "title": "Высокий риск записи",
        "text": summary,
        "impact_label": "",
        "affected_names": affected_names,
        "extra_affected_count": extra_affected_count,
        "substitution_label": "",
    }

def _build_calendar_risk_details(employee_id, employee_issue_meta, issue_label, issue_description, employee_names_by_id):
    has_conflict = employee_issue_meta["has_conflict"]
    has_high_risk = employee_issue_meta["has_high_risk"]
    status = "conflict" if has_conflict else ("risk" if has_high_risk else "clear")
    if has_conflict:
        summary = "В выбранном периоде есть конфликт состава. Причины показаны ниже."
    elif has_high_risk:
        summary = "Критического конфликта нет, но есть фактор высокого риска."
    else:
        summary = "В выбранном периоде критичных проблем не найдено."

    conflict_events = _combine_group_staffing_events(employee_issue_meta.get("conflict_events", []))
    conflict_groups = _group_staffing_issue_events(conflict_events)
    risk_groups = _group_staffing_issue_events(employee_issue_meta.get("risk_events", []))
    used_risk_group_indexes = set()
    problems = []
    for conflict_group in conflict_groups:
        substitution_groups = []
        for risk_group_index, risk_group in enumerate(risk_groups):
            if risk_group_index in used_risk_group_indexes:
                continue
            if risk_group["event"].get("kind") != "substitution_used":
                continue
            if not _groups_share_scope(conflict_group, risk_group):
                continue
            if not _group_dates_overlap(conflict_group, risk_group):
                continue
            used_risk_group_indexes.add(risk_group_index)
            substitution_groups.append(risk_group)
        problems.append(_build_problem_from_group(conflict_group, employee_names_by_id, substitution_groups))

    for risk_group_index, risk_group in enumerate(risk_groups):
        if risk_group_index in used_risk_group_indexes:
            continue
        problems.append(_build_problem_from_group(risk_group, employee_names_by_id))

    if has_high_risk and employee_issue_meta["risk_summary"] and not risk_groups:
        problems.append(_build_fallback_risk_problem(employee_issue_meta["risk_summary"], employee_id, employee_names_by_id))

    return {
        "status": status,
        "label": issue_label,
        "summary": summary,
        "problems": problems,
        "reasons": problems,
    }

def _build_calendar_issue_meta(employees, employee_entries, issue_employee_entries, period_start, period_end):
    issue_meta = {
        employee.id: {
            "has_high_risk": False,
            "has_conflict": False,
            "risk_summary": "",
            "conflict_summary": "",
            "conflict_dates": set(),
            "risk_events": [],
            "conflict_events": [],
        }
        for employee in employees
    }
    for employee in employees:
        for entry in employee_entries.get(employee.id, []):
            if _entry_overlaps_period(entry, period_start, period_end) and entry.get("risk_level") == VacationRequest.RISK_HIGH:
                issue_meta[employee.id]["has_high_risk"] = True
                issue_meta[employee.id]["risk_summary"] = f'Высокий риск: {entry.get("risk_score", 0)}%'
                break

    staffing_issue_meta = _get_staffing_issue_meta(
        employees,
        issue_employee_entries or employee_entries,
        period_start,
        period_end,
    )
    substitution_risk_meta = staffing_issue_meta["substitution_risks"]
    for employee_id, meta in substitution_risk_meta.items():
        if employee_id in issue_meta:
            issue_meta[employee_id]["has_high_risk"] = True
            if not issue_meta[employee_id]["risk_summary"]:
                issue_meta[employee_id]["risk_summary"] = meta["summary"]
            issue_meta[employee_id]["risk_events"].extend(meta.get("events", []))

    conflict_meta = staffing_issue_meta["conflicts"]
    for employee_id, meta in conflict_meta.items():
        if employee_id in issue_meta:
            issue_meta[employee_id]["has_conflict"] = True
            issue_meta[employee_id]["conflict_summary"] = meta["summary"]
            issue_meta[employee_id]["conflict_dates"] = meta["dates"]
            issue_meta[employee_id]["conflict_events"].extend(meta.get("events", []))

    return issue_meta

def build_calendar_base_data(year, employee_ids=None):
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    employees_queryset = Employees.objects.select_related(
        "department",
        "department__staffing_rule",
        "employee_position",
        "employee_position__production_group",
    ).filter(
        is_active_employee=True,
        date_joined__lte=year_end,
    ).order_by(
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
    records = exclude_converted_paid_requests(
        records,
        employee_ids=employee_ids,
        start_date=year_start,
        end_date=year_end,
    )

    for record in records:
        clipped_period = clip_period_to_range(record.start_date, record.end_date, year_start, year_end)
        if clipped_period is None:
            continue

        clipped_start, clipped_end = clipped_period
        employee = record.employee
        production_group = (
            employee.employee_position.production_group
            if employee.employee_position_id and employee.employee_position
            else None
        )
        display_status = REQUEST_STATUS_TO_DISPLAY_STATUS[record.status]
        display_meta = DISPLAY_STATUS_UI[display_status]
        entry = {
            "employee_id": employee.id,
            "department_id": employee.department_id,
            "source_kind": "request",
            "source_id": record.id,
            "detail_url": reverse("vacation_detail", args=[record.id]),
            "detail_label": "Открыть заявку",
            "employee_name": employee.full_name,
            "employee_position": employee.position,
            "production_group_id": production_group.id if production_group else None,
            "production_group_name": production_group.name if production_group else "Не указана",
            "department_name": employee.department.name if employee.department else "Не указан",
            "status": record.status,
            "risk_score": record.risk_score,
            "risk_level": record.risk_level,
            "risk_label": _risk_label_for_level(record.risk_level),
            "is_active_absence": record.status in VacationRequest.ACTIVE_STATUSES,
            "display_status": display_status,
            "display_type": display_meta["display_type"],
            "display_label": display_meta["label"],
            "status_label": display_meta["label"],
            "source_label": display_meta["source_label"],
            "css_class": display_meta["css_class"],
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
            current_status = employee_day_status[employee.id].get(current_date, DISPLAY_FREE)
            if DISPLAY_STATUS_PRIORITY[display_status] >= DISPLAY_STATUS_PRIORITY[current_status]:
                employee_day_status[employee.id][current_date] = display_status

    schedule_items = VacationScheduleItem.objects.select_related(
        "employee",
        "employee__department",
        "employee__employee_position",
        "employee__employee_position__production_group",
        "schedule",
        "created_from_vacation_request",
    ).filter(
        start_date__lte=year_end,
        end_date__gte=year_start,
        status__in=SCHEDULE_STATUS_TO_DISPLAY_STATUS.keys(),
    )
    if employee_ids is not None:
        schedule_items = schedule_items.filter(employee_id__in=employee_ids)

    for item in schedule_items:
        if item.employee_id not in employee_entries:
            continue

        clipped_period = clip_period_to_range(item.start_date, item.end_date, year_start, year_end)
        if clipped_period is None:
            continue

        clipped_start, clipped_end = clipped_period
        employee = item.employee
        production_group = (
            employee.employee_position.production_group
            if employee.employee_position_id and employee.employee_position
            else None
        )
        calendar_status = SCHEDULE_STATUS_TO_CALENDAR_STATUS[item.status]
        display_status = SCHEDULE_STATUS_TO_DISPLAY_STATUS[item.status]
        display_meta = DISPLAY_STATUS_UI[display_status]
        entry = {
            "employee_id": employee.id,
            "department_id": employee.department_id,
            "source_kind": "schedule",
            "source_id": item.id,
            "detail_url": reverse("vacation_detail", args=[item.created_from_vacation_request_id])
            if item.created_from_vacation_request_id
            else "",
            "detail_label": "Открыть заявку" if item.created_from_vacation_request_id else "",
            "employee_name": employee.full_name,
            "employee_position": employee.position,
            "production_group_id": production_group.id if production_group else None,
            "production_group_name": production_group.name if production_group else "Не указана",
            "department_name": employee.department.name if employee.department else "Не указан",
            "status": calendar_status,
            "schedule_status": item.status,
            "risk_score": item.risk_score,
            "risk_level": item.risk_level,
            "risk_label": _risk_label_for_level(item.risk_level),
            "is_active_absence": item.status in VacationScheduleItem.ACTIVE_STATUSES,
            "display_status": display_status,
            "display_type": display_meta["display_type"],
            "display_label": display_meta["label"],
            "status_label": display_meta["label"],
            "source_label": _schedule_item_source_label(item),
            "css_class": display_meta["css_class"],
            "status_icon": REQUEST_STATUS_UI[calendar_status]["icon"],
            "vacation_type_label": item.get_vacation_type_display(),
            "start_date": clipped_start,
            "end_date": clipped_end,
            "days": get_requested_days(clipped_start, clipped_end),
            "period_label": format_period_label(clipped_start, clipped_end),
            "sort_key": clipped_start.toordinal(),
        }
        employee_entries[employee.id].append(entry)

        for current_date in iterate_dates(clipped_start, clipped_end):
            current_status = employee_day_status[employee.id].get(current_date, DISPLAY_FREE)
            if DISPLAY_STATUS_PRIORITY[display_status] >= DISPLAY_STATUS_PRIORITY[current_status]:
                employee_day_status[employee.id][current_date] = display_status

    for employee_id, entries in employee_entries.items():
        entries.sort(key=lambda item: (item["sort_key"], -DISPLAY_STATUS_PRIORITY[item["display_status"]]))

    return employees, employee_day_status, employee_entries

def _empty_calendar_display_counts():
    counts = {
        "schedule_days": 0,
        "request_days": 0,
        "changed_days": 0,
        "total_days": 0,
        "display_statuses": set(),
    }
    for status in (
        VacationRequest.STATUS_APPROVED,
        VacationRequest.STATUS_PENDING,
        VacationRequest.STATUS_REJECTED,
    ):
        counts[status] = 0
    return counts

def _add_entry_to_display_counts(counts, entry, days):
    if days <= 0:
        return

    counts["total_days"] += days
    counts["display_statuses"].add(entry["display_status"])
    if entry["status"] in (
        VacationRequest.STATUS_APPROVED,
        VacationRequest.STATUS_PENDING,
        VacationRequest.STATUS_REJECTED,
    ):
        counts[entry["status"]] += days

    if entry["display_type"] == "request":
        counts["request_days"] += days
    elif entry["display_status"] in (DISPLAY_SCHEDULE_TRANSFERRED, DISPLAY_SCHEDULE_CANCELLED):
        counts["changed_days"] += days
    else:
        counts["schedule_days"] += days

def _get_display_status_from_counts(counts):
    statuses = counts["display_statuses"]
    if len(statuses) > 1:
        return DISPLAY_MIXED
    if statuses:
        return next(iter(statuses))
    return DISPLAY_FREE

def _serialize_calendar_entry(
    entry,
    current_employee_id=None,
    today=None,
    conflict_dates=None,
    conflict_summary="",
    risk_summary="",
):
    today = today or timezone.localdate()
    conflict_dates = conflict_dates or set()
    entry_dates = {
        current_date.isoformat()
        for current_date in iterate_dates(entry["start_date"], entry["end_date"])
    }
    has_conflict = bool(entry_dates & conflict_dates)
    can_request_transfer = (
        entry.get("source_kind") == "schedule"
        and entry.get("schedule_status") in VacationScheduleItem.ACTIVE_STATUSES
        and entry["start_date"] > today
        and entry["employee_id"] == current_employee_id
    )
    payload = {
        "source_kind": entry.get("source_kind", ""),
        "source_id": entry.get("source_id"),
        "detail_url": entry.get("detail_url", ""),
        "detail_label": entry.get("detail_label", ""),
        "period_label": entry["period_label"],
        "status_label": entry["status_label"],
        "display_label": entry["display_label"],
        "source_label": entry["source_label"],
        "display_type": entry["display_type"],
        "status": entry["display_status"],
        "css_class": entry["css_class"],
        "risk_score": entry.get("risk_score", 0),
        "risk_level": entry.get("risk_level", VacationRequest.RISK_LOW),
        "risk_label": entry.get("risk_label") or _risk_label_for_level(entry.get("risk_level", VacationRequest.RISK_LOW)),
        "has_high_risk": entry.get("risk_level") == VacationRequest.RISK_HIGH,
        "has_conflict": has_conflict,
        "conflict_summary": conflict_summary if has_conflict else "",
        "risk_short_reason": "" if has_conflict else (risk_summary if entry.get("risk_level") == VacationRequest.RISK_HIGH else ""),
        "anchor": _build_entry_anchor(entry),
        "vacation_type_label": entry["vacation_type_label"],
        "days": entry["days"],
        "can_request_transfer": can_request_transfer,
    }
    if can_request_transfer:
        payload["transfer_url"] = reverse("schedule_change_request_create", args=[entry["source_id"]])
        payload["transfer_title"] = f'{entry["period_label"]} · {entry["vacation_type_label"]}'
    return payload

def build_month_timeline_cells(day_map, year, month, today):
    days_in_month = calendar.monthrange(year, month)[1]
    cells = []
    for day in range(1, days_in_month + 1):
        current_date = date(year, month, day)
        status = day_map.get(current_date, DISPLAY_FREE)
        previous_status = day_map.get(current_date - timedelta(days=1), DISPLAY_FREE) if day > 1 else DISPLAY_FREE
        next_status = day_map.get(current_date + timedelta(days=1), DISPLAY_FREE) if day < days_in_month else DISPLAY_FREE
        is_start = status != DISPLAY_FREE and previous_status != status
        is_end = status != DISPLAY_FREE and next_status != status
        cells.append(
            {
                "day": day,
                "date_iso": current_date.isoformat(),
                "status": status,
                "display_status": status,
                "css_class": DISPLAY_STATUS_UI[status]["css_class"],
                "is_weekend": current_date.weekday() >= 5,
                "is_today": current_date == today,
                "is_start": is_start,
                "is_end": is_end,
                "is_single": is_start and is_end,
                "tooltip": f'{day:02d}.{month:02d}.{year} • {VACATION_STATUS_META[status]["label"]}',
            }
        )
    return cells

def build_year_month_cells(entries, year, conflict_dates=None):
    conflict_dates = conflict_dates or set()
    month_cells = []
    for month_number in range(1, 13):
        month_start = date(year, month_number, 1)
        month_end = get_month_end(month_start)
        days_in_month = calendar.monthrange(year, month_number)[1]
        counts = _empty_calendar_display_counts()
        segments = []
        has_high_risk = False
        has_conflict = False
        for entry in entries:
            overlap = clip_period_to_range(entry["start_date"], entry["end_date"], month_start, month_end)
            if overlap is None:
                continue

            overlap_start, overlap_end = overlap
            overlap_days = get_requested_days(overlap_start, overlap_end)
            _add_entry_to_display_counts(counts, entry, overlap_days)
            if entry.get("risk_level") == VacationRequest.RISK_HIGH:
                has_high_risk = True
            if any(current_date.isoformat() in conflict_dates for current_date in iterate_dates(overlap_start, overlap_end)):
                has_conflict = True

            segments.append(
                {
                    "status": entry["display_status"],
                    "display_status": entry["display_status"],
                    "css_class": entry["css_class"],
                    "days": overlap_days,
                    "offset_percent": round(((overlap_start.day - 1) / days_in_month) * 100, 1),
                    "width_percent": round((overlap_days / days_in_month) * 100, 1),
                }
            )

        busy_days = counts["total_days"]
        status_key = _get_display_status_from_counts(counts)

        segments.sort(
            key=lambda segment: (
                segment["offset_percent"],
                -DISPLAY_STATUS_PRIORITY.get(segment["status"], 0),
            )
        )

        month_cells.append(
            {
                "month_name": RUSSIAN_MONTH_NAMES[month_number - 1],
                "month_short": RUSSIAN_MONTH_SHORT_NAMES[month_number - 1],
                "month_number": month_number,
                "busy_days": busy_days,
                "status": status_key,
                "display_status": status_key,
                "schedule_days": counts["schedule_days"],
                "request_days": counts["request_days"],
                "changed_days": counts["changed_days"],
                "has_high_risk": has_high_risk,
                "has_conflict": has_conflict,
                "segments": segments,
                "approved_days": counts[VacationRequest.STATUS_APPROVED],
                "pending_days": counts[VacationRequest.STATUS_PENDING],
                "rejected_days": counts[VacationRequest.STATUS_REJECTED],
            }
        )

    return month_cells

def build_calendar_rows(
    employees,
    employee_day_status,
    employee_entries,
    year,
    month,
    view_mode,
    today,
    current_employee=None,
    issue_employee_entries=None,
    issue_filter="all",
):
    period_start = date(year, 1, 1) if view_mode == "year" else date(year, month, 1)
    period_end = date(year, 12, 31) if view_mode == "year" else date(year, month, calendar.monthrange(year, month)[1])
    rows = []
    details = {}
    issue_meta = _build_calendar_issue_meta(
        employees,
        employee_entries,
        issue_employee_entries,
        period_start,
        period_end,
    )
    employee_names_by_id = {employee.id: employee.full_name for employee in employees}
    for entries_by_employee in (employee_entries, issue_employee_entries or {}):
        for entries in entries_by_employee.values():
            for entry in entries:
                if entry.get("employee_name"):
                    employee_names_by_id.setdefault(entry["employee_id"], entry["employee_name"])

    for employee in employees:
        day_map = employee_day_status.get(employee.id, {})
        entries = employee_entries.get(employee.id, [])
        identity = get_employee_identity_presentation(employee)
        profile_url = reverse("employee_profile", args=[employee.id])

        selected_entries = [
            entry for entry in entries if clip_period_to_range(entry["start_date"], entry["end_date"], period_start, period_end)
        ]
        upcoming_entry = next((entry for entry in entries if entry["end_date"] >= today), None)
        period_counts = _empty_calendar_display_counts()
        year_counts = _empty_calendar_display_counts()
        year_start = date(year, 1, 1)
        year_end = date(year, 12, 31)
        for entry in entries:
            year_overlap = clip_period_to_range(entry["start_date"], entry["end_date"], year_start, year_end)
            if year_overlap is not None:
                _add_entry_to_display_counts(year_counts, entry, get_requested_days(*year_overlap))
            period_overlap = clip_period_to_range(entry["start_date"], entry["end_date"], period_start, period_end)
            if period_overlap is not None:
                _add_entry_to_display_counts(period_counts, entry, get_requested_days(*period_overlap))

        row_status = _get_display_status_from_counts(period_counts)
        employee_issue_meta = issue_meta.get(
            employee.id,
            {
                "has_high_risk": False,
                "has_conflict": False,
                "risk_summary": "",
                "conflict_summary": "",
                "conflict_dates": set(),
                "risk_events": [],
                "conflict_events": [],
            },
        )
        if issue_filter == "risk" and not employee_issue_meta["has_high_risk"]:
            continue
        if issue_filter == "conflict" and not employee_issue_meta["has_conflict"]:
            continue
        issue_label = "Конфликт" if employee_issue_meta["has_conflict"] else (
            "Высокий риск" if employee_issue_meta["has_high_risk"] else "Проблем нет"
        )
        issue_description = employee_issue_meta["conflict_summary"] or employee_issue_meta["risk_summary"] or "В выбранном периоде критичных проблем не найдено."
        risk_details = _build_calendar_risk_details(
            employee.id,
            employee_issue_meta,
            issue_label,
            issue_description,
            employee_names_by_id,
        )
        issue_chips = _build_row_issue_chips(employee_issue_meta, issue_filter)
        is_year_view = view_mode == "year"
        selected_entry_identities = {_entry_identity(entry) for entry in selected_entries}
        secondary_entries = [] if is_year_view else [
            entry for entry in entries if _entry_identity(entry) not in selected_entry_identities
        ]
        serialized_selected_entries = [
            _serialize_calendar_entry(
                entry,
                getattr(current_employee, "id", None),
                today,
                employee_issue_meta["conflict_dates"],
                employee_issue_meta["conflict_summary"],
                employee_issue_meta["risk_summary"],
            )
            for entry in selected_entries
        ]
        serialized_year_entries = [
            _serialize_calendar_entry(
                entry,
                getattr(current_employee, "id", None),
                today,
                employee_issue_meta["conflict_dates"],
                employee_issue_meta["conflict_summary"],
                employee_issue_meta["risk_summary"],
            )
            for entry in entries
        ]
        serialized_primary_entries = serialized_year_entries if is_year_view else serialized_selected_entries
        serialized_secondary_entries = [
            _serialize_calendar_entry(
                entry,
                getattr(current_employee, "id", None),
                today,
                employee_issue_meta["conflict_dates"],
                employee_issue_meta["conflict_summary"],
                employee_issue_meta["risk_summary"],
            )
            for entry in secondary_entries
        ]

        rows.append(
            {
                "employee_id": employee.id,
                "employee_name": employee.full_name,
                "profile_url": profile_url,
                "role_icon": identity["employee_role_icon"],
                "role_icon_type": identity["employee_role_icon_type"],
                "role_variant": identity["employee_role_variant"],
                "role_label": identity["employee_role_label"],
                "has_high_risk": employee_issue_meta["has_high_risk"],
                "has_conflict": employee_issue_meta["has_conflict"],
                "issue_label": issue_label,
                "issue_description": issue_description,
                "issue_chips": issue_chips,
                "position": employee.position,
                "production_group": identity["employee_production_group_label"],
                "department": identity["employee_department_label"],
                "employee_department_label": identity["employee_department_label"],
                "employee_production_group_label": identity["employee_production_group_label"],
                "employee_management_badges": identity["employee_management_badges"],
                "status": row_status,
                "display_status": row_status,
                "selected_schedule_days": period_counts["schedule_days"],
                "selected_request_days": period_counts["request_days"],
                "selected_changed_days": period_counts["changed_days"],
                "selected_total_days": period_counts["total_days"],
                "selected_approved_days": period_counts[VacationRequest.STATUS_APPROVED],
                "selected_pending_days": period_counts[VacationRequest.STATUS_PENDING],
                "selected_rejected_days": period_counts[VacationRequest.STATUS_REJECTED],
                "year_schedule_days": year_counts["schedule_days"],
                "year_request_days": year_counts["request_days"],
                "year_changed_days": year_counts["changed_days"],
                "year_total_days": year_counts["total_days"],
                "year_approved_days": year_counts[VacationRequest.STATUS_APPROVED],
                "year_pending_days": year_counts[VacationRequest.STATUS_PENDING],
                "year_rejected_days": year_counts[VacationRequest.STATUS_REJECTED],
                "cells": build_year_month_cells(entries, year, employee_issue_meta["conflict_dates"])
                if view_mode == "year"
                else build_month_timeline_cells(day_map, year, month, today),
            }
        )

        details[str(employee.id)] = {
            "employee_name": employee.full_name,
            "position": employee.position,
            "production_group": identity["employee_production_group_label"],
            "department": identity["employee_department_label"],
            "profile_url": profile_url,
            "role_icon": identity["employee_role_icon"],
            "role_icon_type": identity["employee_role_icon_type"],
            "role_variant": identity["employee_role_variant"],
            "role_label": identity["employee_role_label"],
            "employee_management_badges": identity["employee_management_badges"],
            "has_high_risk": employee_issue_meta["has_high_risk"],
            "has_conflict": employee_issue_meta["has_conflict"],
            "issue_label": issue_label,
            "issue_description": issue_description,
            "risk_summary": employee_issue_meta["risk_summary"],
            "conflict_summary": employee_issue_meta["conflict_summary"],
            "risk_details": risk_details,
            "view_mode": view_mode,
            "is_year_view": is_year_view,
            "selected_period_label": f"{RUSSIAN_MONTH_NAMES[month - 1]} {year}" if view_mode == "month" else f"Годовой обзор {year}",
            "selected_schedule_days": period_counts["schedule_days"],
            "selected_request_days": period_counts["request_days"],
            "selected_changed_days": period_counts["changed_days"],
            "selected_total_days": period_counts["total_days"],
            "selected_approved_days": period_counts[VacationRequest.STATUS_APPROVED],
            "selected_pending_days": period_counts[VacationRequest.STATUS_PENDING],
            "selected_rejected_days": period_counts[VacationRequest.STATUS_REJECTED],
            "year_schedule_days": year_counts["schedule_days"],
            "year_request_days": year_counts["request_days"],
            "year_changed_days": year_counts["changed_days"],
            "year_total_days": year_counts["total_days"],
            "year_approved_days": year_counts[VacationRequest.STATUS_APPROVED],
            "year_pending_days": year_counts[VacationRequest.STATUS_PENDING],
            "year_rejected_days": year_counts[VacationRequest.STATUS_REJECTED],
            "upcoming_label": upcoming_entry["period_label"] if upcoming_entry else "Ближайший отпуск не запланирован",
            "upcoming_status": upcoming_entry["status_label"] if upcoming_entry else "",
            "upcoming_anchor": _build_entry_anchor(upcoming_entry) if upcoming_entry else None,
            "primary_entries_title": "Записи за год" if is_year_view else "Отпуска в выбранном месяце",
            "primary_entries_empty": "За этот год записей пока нет." if is_year_view else "В выбранном месяце отпусков нет.",
            "primary_entries": serialized_primary_entries,
            "secondary_entries_title": "Остальные записи за год",
            "secondary_entries_empty": "Других записей за год нет.",
            "secondary_entries": serialized_secondary_entries,
            "selected_entries": serialized_selected_entries,
            "year_entries": serialized_year_entries,
        }
        details[str(employee.id)]["selected_period_label"] = (
            f"{RUSSIAN_MONTH_NAMES[month - 1]} {year}" if view_mode == "month" else f"Годовой обзор {year}"
        )
        if upcoming_entry is None:
            details[str(employee.id)]["upcoming_label"] = "Ближайший отпуск не запланирован"

    return rows, details

def build_calendar_month_totals(calendar_rows):
    totals = []
    for month_number, month_short in enumerate(RUSSIAN_MONTH_SHORT_NAMES, start=1):
        employee_count = 0
        busy_days = 0
        risk_count = 0
        conflict_count = 0

        for row in calendar_rows:
            cells = row.get("cells") or []
            if len(cells) < month_number:
                continue

            cell = cells[month_number - 1]
            cell_busy_days = cell.get("busy_days", 0)
            if cell_busy_days:
                employee_count += 1
                busy_days += cell_busy_days
            if cell.get("has_high_risk"):
                risk_count += 1
            if cell.get("has_conflict"):
                conflict_count += 1

        totals.append(
            {
                "month_number": month_number,
                "month_short": month_short,
                "employee_count": employee_count,
                "busy_days": busy_days,
                "risk_count": risk_count,
                "conflict_count": conflict_count,
            }
        )

    return totals

def build_calendar_summary(employee_entries, year, month, view_mode):
    period_start = date(year, 1, 1) if view_mode == "year" else date(year, month, 1)
    period_end = date(year, 12, 31) if view_mode == "year" else date(year, month, calendar.monthrange(year, month)[1])
    employees_in_period = set()
    counts = _empty_calendar_display_counts()

    for entries in employee_entries.values():
        for entry in entries:
            overlap = clip_period_to_range(entry["start_date"], entry["end_date"], period_start, period_end)
            if overlap is None:
                continue

            overlap_start, overlap_end = overlap
            overlap_days = get_requested_days(overlap_start, overlap_end)
            employees_in_period.add(entry["employee_id"])
            _add_entry_to_display_counts(counts, entry, overlap_days)

    return [
        {
            "icon": "groups",
            "label": "Сотрудников в периоде",
            "value": len(employees_in_period),
            "hint": "У кого есть отпуск или заявка в выбранном диапазоне.",
        },
        {
            "icon": "event_available",
            "label": "По годовому графику",
            "value": counts["schedule_days"],
            "hint": "Дни из утвержденного или запланированного графика отпусков.",
        },
        {
            "icon": "watch_later",
            "label": "Заявки и изменения",
            "value": counts["request_days"] + counts["changed_days"],
            "hint": "Внеплановые заявки, переносы и отмененные пункты графика.",
        },
    ]
