import calendar
from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Count
from django.urls import reverse
from django.utils import timezone

from apps.employees.models import DepartmentCoverageRule, Departments, Employees, ProductionGroupSubstitutionRule
from apps.employees.role_presentation import get_employee_role_card_meta
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
from .querysets import exclude_converted_paid_requests, get_vacation_requests_queryset

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

def _get_department_staffing_rule(department):
    if department is None:
        return None

    try:
        return department.staffing_rule
    except department.__class__.staffing_rule.RelatedObjectDoesNotExist:
        return None

def _get_staffing_limits_for_date(department, current_date, workload_by_department_month, staffing_rules):
    workload = workload_by_department_month.get((department.id, current_date.year, current_date.month))
    if workload is not None:
        return workload.min_staff_required, workload.max_absent

    staffing_rule = staffing_rules.get(department.id)
    if staffing_rule is not None:
        return staffing_rule.min_staff_required, staffing_rule.max_absent

    return 0, 1

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

def _get_staffing_issue_meta(employees, employee_entries, period_start, period_end):
    department_by_id = {employee.department_id: employee.department for employee in employees if employee.department_id}
    if not department_by_id:
        return {"conflicts": {}, "substitution_risks": {}}

    department_ids = set(department_by_id)
    staffing_rules = {
        department_id: _get_department_staffing_rule(department)
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
    staff_counts = {
        row["department_id"]: row["total"]
        for row in Employees.objects.filter(
            department_id__in=department_ids,
            is_active_employee=True,
            date_joined__lte=period_end,
        )
        .exclude(role__in=Employees.SERVICE_ROLES)
        .values("department_id")
        .annotate(total=Count("id"))
    }
    staff_members = list(
        Employees.objects.select_related(
            "employee_position",
            "employee_position__production_group",
        ).filter(
            department_id__in=department_ids,
            is_active_employee=True,
            date_joined__lte=period_end,
        ).exclude(role__in=Employees.SERVICE_ROLES)
    )
    staff_ids_by_group = defaultdict(set)
    for staff_member in staff_members:
        group_id = (
            staff_member.employee_position.production_group_id
            if staff_member.employee_position_id and staff_member.employee_position
            else None
        )
        if group_id is not None:
            staff_ids_by_group[(staff_member.department_id, group_id)].add(staff_member.id)

    coverage_rules_by_department = defaultdict(list)
    coverage_rule_by_group = {}
    for rule in DepartmentCoverageRule.objects.select_related("production_group").filter(department_id__in=department_ids):
        coverage_rules_by_department[rule.department_id].append(rule)
        coverage_rule_by_group[(rule.department_id, rule.production_group_id)] = rule

    substitution_rules_by_source = defaultdict(list)
    for rule in ProductionGroupSubstitutionRule.objects.select_related("substitute_group").filter(department_id__in=department_ids):
        substitution_rules_by_source[(rule.department_id, rule.source_group_id)].append(rule)

    leadership_by_department = {
        row["id"]: row
        for row in Departments.objects.filter(id__in=department_ids).values("id", "head_id", "deputy_id")
    }
    enterprise_head_ids = set(
        Employees.objects.filter(
            role=Employees.ROLE_ENTERPRISE_HEAD,
            is_active_employee=True,
            date_joined__lte=period_end,
        ).values_list("id", flat=True)
    )
    enterprise_deputy_ids = set(
        Employees.objects.filter(
            is_enterprise_deputy=True,
            is_active_employee=True,
            date_joined__lte=period_end,
        ).exclude(role__in=Employees.SERVICE_ROLES).values_list("id", flat=True)
    )

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

    conflict_meta = defaultdict(lambda: {"summaries": [], "dates": set()})
    substitution_risk_meta = defaultdict(lambda: {"summaries": [], "dates": set()})
    def add_conflict(employee_ids, current_date, reason):
        for employee_id in employee_ids:
            conflict_meta[employee_id]["dates"].add(current_date.isoformat())
            if reason not in conflict_meta[employee_id]["summaries"]:
                conflict_meta[employee_id]["summaries"].append(reason)

    def add_substitution_risk(employee_ids, current_date, reason):
        for employee_id in employee_ids:
            substitution_risk_meta[employee_id]["dates"].add(current_date.isoformat())
            if reason not in substitution_risk_meta[employee_id]["summaries"]:
                substitution_risk_meta[employee_id]["summaries"].append(reason)

    for (department_id, current_date), absent_employee_ids in absent_by_department_day.items():
        department = department_by_id[department_id]
        min_staff_required, max_absent = _get_staffing_limits_for_date(
            department,
            current_date,
            workload_by_department_month,
            staffing_rules,
        )
        staff_count = staff_counts.get(department_id, 0)
        absent_count = len(absent_employee_ids)
        remaining_staff_count = max(staff_count - absent_count, 0)
        exceeds_absent_limit = bool(max_absent and absent_count > max_absent)
        breaks_minimum_staff = bool(min_staff_required and remaining_staff_count < min_staff_required)
        if exceeds_absent_limit or breaks_minimum_staff:
            reason = _format_conflict_reason(
                current_date,
                absent_count,
                max_absent,
                remaining_staff_count,
                min_staff_required,
            )
            add_conflict(absent_employee_ids, current_date, reason)

        present_ids_by_group = {}
        substitute_capacity_remaining = {}
        for staff_group_key, group_staff_ids_for_capacity in staff_ids_by_group.items():
            staff_department_id, staff_group_id = staff_group_key
            if staff_department_id != department_id:
                continue
            present_ids = group_staff_ids_for_capacity - absent_employee_ids
            present_ids_by_group[staff_group_id] = present_ids
            group_rule = coverage_rule_by_group.get((department_id, staff_group_id))
            group_minimum = group_rule.min_staff_required if group_rule is not None else 0
            substitute_capacity_remaining[staff_group_id] = max(len(present_ids) - group_minimum, 0)

        sorted_coverage_rules = sorted(
            coverage_rules_by_department.get(department_id, []),
            key=lambda rule: (-rule.criticality_level, rule.production_group.name),
        )
        for coverage_rule in sorted_coverage_rules:
            group_id = coverage_rule.production_group_id
            group_staff_ids = staff_ids_by_group.get((department_id, group_id), set())
            if not group_staff_ids:
                continue

            absent_group_ids = group_staff_ids & absent_employee_ids
            present_primary_ids = present_ids_by_group.get(group_id, set())
            primary_present_count = len(present_primary_ids)
            shortage = max(coverage_rule.min_staff_required - primary_present_count, 0)
            covered_by_substitution = 0
            if shortage:
                for substitution_rule in substitution_rules_by_source.get((department_id, group_id), []):
                    substitute_group_id = substitution_rule.substitute_group_id
                    available_capacity = substitute_capacity_remaining.get(substitute_group_id, 0)
                    if available_capacity <= 0:
                        continue
                    covered_now = min(
                        shortage - covered_by_substitution,
                        available_capacity,
                        substitution_rule.max_covered_absences,
                    )
                    if covered_now <= 0:
                        continue
                    covered_by_substitution += covered_now
                    substitute_capacity_remaining[substitute_group_id] = available_capacity - covered_now
                    if covered_by_substitution >= shortage:
                        break

            effective_present_count = primary_present_count + covered_by_substitution
            absent_group_count = len(absent_group_ids)
            breaks_group_minimum = bool(
                coverage_rule.min_staff_required
                and effective_present_count < coverage_rule.min_staff_required
            )
            exceeds_group_absent_limit = bool(absent_group_count > coverage_rule.max_absent)
            if shortage and covered_by_substitution:
                reason = _format_substitution_risk_reason(
                    current_date,
                    coverage_rule.production_group.name,
                    covered_by_substitution,
                )
                add_substitution_risk(absent_group_ids or absent_employee_ids, current_date, reason)
            if breaks_group_minimum or exceeds_group_absent_limit:
                reason = _format_group_conflict_reason(
                    current_date,
                    coverage_rule.production_group.name,
                    effective_present_count,
                    coverage_rule.min_staff_required,
                    absent_group_count,
                    coverage_rule.max_absent,
                )
                add_conflict(absent_group_ids or absent_employee_ids, current_date, reason)

        leadership = leadership_by_department.get(department_id, {})
        head_id = leadership.get("head_id")
        deputy_id = leadership.get("deputy_id")
        if head_id and deputy_id and head_id in absent_employee_ids and deputy_id in absent_employee_ids:
            reason = f'{current_date.strftime("%d.%m.%Y")}: руководитель отдела и заместитель отсутствуют'
            add_conflict({head_id, deputy_id}, current_date, reason)

    for current_date, absent_employee_ids in absent_by_day.items():
        absent_enterprise_heads = enterprise_head_ids & absent_employee_ids
        absent_enterprise_deputies = enterprise_deputy_ids & absent_employee_ids
        if absent_enterprise_heads and absent_enterprise_deputies:
            reason = f'{current_date.strftime("%d.%m.%Y")}: руководитель предприятия и заместитель отсутствуют'
            add_conflict(absent_enterprise_heads | absent_enterprise_deputies, current_date, reason)

    return {
        "conflicts": {
            employee_id: {
                "dates": meta["dates"],
                "summary": "; ".join(meta["summaries"][:2]),
            }
            for employee_id, meta in conflict_meta.items()
        },
        "substitution_risks": {
            employee_id: {
                "dates": meta["dates"],
                "summary": "; ".join(meta["summaries"][:2]),
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

def _build_calendar_issue_meta(employees, employee_entries, issue_employee_entries, period_start, period_end):
    issue_meta = {
        employee.id: {
            "has_high_risk": False,
            "has_conflict": False,
            "risk_summary": "",
            "conflict_summary": "",
            "conflict_dates": set(),
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

    conflict_meta = staffing_issue_meta["conflicts"]
    for employee_id, meta in conflict_meta.items():
        if employee_id in issue_meta:
            issue_meta[employee_id]["has_conflict"] = True
            issue_meta[employee_id]["conflict_summary"] = meta["summary"]
            issue_meta[employee_id]["conflict_dates"] = meta["dates"]

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

def _serialize_calendar_entry(entry, current_employee_id=None, today=None, conflict_dates=None, conflict_summary=""):
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

    for employee in employees:
        day_map = employee_day_status.get(employee.id, {})
        entries = employee_entries.get(employee.id, [])
        role_meta = get_employee_role_card_meta(employee)
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
        issue_chips = _build_row_issue_chips(employee_issue_meta, issue_filter)

        rows.append(
            {
                "employee_id": employee.id,
                "employee_name": employee.full_name,
                "profile_url": profile_url,
                "role_icon": role_meta["icon"],
                "role_icon_type": role_meta["icon_type"],
                "role_variant": role_meta["variant"],
                "role_label": role_meta["label"],
                "has_high_risk": employee_issue_meta["has_high_risk"],
                "has_conflict": employee_issue_meta["has_conflict"],
                "issue_label": issue_label,
                "issue_description": issue_description,
                "issue_chips": issue_chips,
                "position": employee.position,
                "production_group": (
                    employee.employee_position.production_group.name
                    if employee.employee_position_id and employee.employee_position
                    else "Не указана"
                ),
                "department": employee.department.name if employee.department else "Не указан",
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
            "production_group": (
                employee.employee_position.production_group.name
                if employee.employee_position_id and employee.employee_position
                else "Не указана"
            ),
            "department": employee.department.name if employee.department else "Не указан",
            "profile_url": profile_url,
            "role_icon": role_meta["icon"],
            "role_icon_type": role_meta["icon_type"],
            "role_variant": role_meta["variant"],
            "role_label": role_meta["label"],
            "has_high_risk": employee_issue_meta["has_high_risk"],
            "has_conflict": employee_issue_meta["has_conflict"],
            "issue_label": issue_label,
            "issue_description": issue_description,
            "risk_summary": employee_issue_meta["risk_summary"],
            "conflict_summary": employee_issue_meta["conflict_summary"],
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
            "selected_entries": [
                _serialize_calendar_entry(
                    entry,
                    getattr(current_employee, "id", None),
                    today,
                    employee_issue_meta["conflict_dates"],
                    employee_issue_meta["conflict_summary"],
                )
                for entry in selected_entries
            ],
            "year_entries": [
                _serialize_calendar_entry(
                    entry,
                    getattr(current_employee, "id", None),
                    today,
                    employee_issue_meta["conflict_dates"],
                    employee_issue_meta["conflict_summary"],
                )
                for entry in entries
            ],
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
