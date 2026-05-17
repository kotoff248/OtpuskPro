import calendar
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from math import ceil
from types import SimpleNamespace
from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Avg
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from apps.accounts.services import get_managed_department_id, is_department_head_employee, is_hr_employee
from apps.leave.models import (
    DepartmentWorkload,
    VacationPreference,
    VacationPreferenceCollection,
    VacationRequest,
    VacationSchedule,
    VacationScheduleCandidate,
    VacationScheduleCandidatePackage,
    VacationScheduleCandidatePackagePeriod,
    VacationScheduleDepartmentApproval,
    VacationScheduleGenerationRun,
    VacationScheduleItem,
    VacationScheduleManualSuggestionCache,
)
from apps.leave.services.candidate_feedback import build_schedule_candidate_feedback_context
from apps.leave.services.dates import format_period_label, get_chargeable_leave_days, quantize_leave_days
from apps.leave.services.employee_presentation import get_employee_identity_presentation
from apps.leave.services.ledger import (
    get_employee_available_balance,
    get_employee_entitlement_rows,
    get_employee_entitlement_rows_bulk,
    get_employee_list_leave_summaries,
)
from apps.leave.ml.scoring import ACTIVE_CANDIDATE_SCORER_VERSION, score_candidate_features
from apps.leave.services.preferences import (
    get_eligible_preference_employees,
    get_employee_preference_pair_map,
    get_employee_preference_pair,
    get_employee_preference_state_map,
    get_employee_preference_state,
    get_paid_leave_available_from,
)
from apps.leave.services.planning_cycles import is_active_planning_year
from apps.leave.services.risk import calculate_vacation_request_risk_with_explanation
from apps.leave.services.schedule_auto_place_jobs import get_active_schedule_auto_place_job, schedule_auto_place_job_page_payload
from apps.leave.services.staffing import format_staff_count
from apps.leave.services.urgent_closures import detect_previous_year_closure_need, get_active_urgent_closure_payload_map
from apps.leave.services.validation import MIN_CONTINUOUS_PAID_LEAVE_DAYS, get_overlapping_requests, get_overlapping_schedule_items

from apps.leave.services.schedule_drafts.constants import *
from apps.leave.services.schedule_drafts.types import *


def _iter_auto_candidate_payloads_for_target(
    employee,
    year,
    placements,
    target_days,
    latest_end,
    *,
    urgent=False,
    allow_short_parts=False,
    max_chargeable_days=None,
    limit=None,
    exclude_schedule_item_ids=None,
):
    target_days = _decimal_to_whole_days(target_days)
    if target_days <= 0:
        return

    planning_start, planning_end = _planning_year_bounds(year)
    start_bound = max(planning_start, get_paid_leave_available_from(employee))
    latest_end = min(latest_end or planning_end, planning_end)
    yielded_count = 0

    for start_date in _candidate_start_dates(
        year,
        employee,
        start_bound,
        latest_end,
        urgent=urgent,
        target_days=target_days,
    ):
        end_date = _end_date_for_chargeable_days(start_date, target_days, latest_end)
        if end_date is None:
            continue
        calendar_days = (end_date - start_date).days + 1
        if not allow_short_parts and calendar_days < MIN_CONTINUOUS_PAID_LEAVE_DAYS:
            continue
        if _has_short_gap_to_employee_placement(placements, employee.id, start_date, end_date):
            continue

        assessment = assess_schedule_draft_candidate(
            employee,
            start_date,
            end_date,
            year,
            placements,
            max_chargeable_days=max_chargeable_days or Decimal(target_days),
            exclude_schedule_item_ids=exclude_schedule_item_ids,
        )
        if not assessment["can_place"]:
            continue

        yield {
            "start_date": start_date,
            "end_date": end_date,
            "assessment": assessment,
            "target_days": Decimal(target_days),
        }
        yielded_count += 1
        if limit is not None and yielded_count >= limit:
            return


def _iter_auto_candidate_payloads_for_need(
    employee,
    year,
    placements,
    target_days,
    latest_end,
    *,
    urgent=False,
    allow_short_parts=False,
    max_chargeable_days=None,
    limit=None,
    exclude_schedule_item_ids=None,
):
    yielded_count = 0
    for option_days in _auto_target_day_options(target_days):
        for candidate in _iter_auto_candidate_payloads_for_target(
            employee,
            year,
            placements,
            option_days,
            latest_end,
            urgent=urgent,
            allow_short_parts=allow_short_parts,
            max_chargeable_days=max_chargeable_days or Decimal(option_days),
            limit=None if limit is None else limit - yielded_count,
            exclude_schedule_item_ids=exclude_schedule_item_ids,
        ):
            yield candidate
            yielded_count += 1
            if limit is not None and yielded_count >= limit:
                return


def _find_auto_candidate(
    employee,
    year,
    placements,
    target_days,
    latest_end,
    *,
    urgent=False,
    allow_short_parts=False,
    exclude_schedule_item_ids=None,
):
    for candidate in _iter_auto_candidate_payloads_for_target(
        employee,
        year,
        placements,
        target_days,
        latest_end,
        urgent=urgent,
        allow_short_parts=allow_short_parts,
        limit=1,
        exclude_schedule_item_ids=exclude_schedule_item_ids,
    ):
        return candidate

    return None


def _find_auto_candidate_for_need(
    employee,
    year,
    placements,
    target_days,
    latest_end,
    *,
    urgent=False,
    allow_short_parts=False,
    exclude_schedule_item_ids=None,
):
    for candidate in _iter_auto_candidate_payloads_for_need(
        employee,
        year,
        placements,
        target_days,
        latest_end,
        urgent=urgent,
        allow_short_parts=allow_short_parts,
        limit=1,
        exclude_schedule_item_ids=exclude_schedule_item_ids,
    ):
        return candidate
    return None


def _iter_adjacent_topup_candidate_payloads(
    employee,
    year,
    placements,
    current_items,
    target_days,
    latest_end,
    *,
    max_chargeable_days=None,
    limit=None,
    exclude_schedule_item_ids=None,
):
    target_days = _decimal_to_whole_days(target_days)
    if target_days <= 0:
        return

    planning_start, planning_end = _planning_year_bounds(year)
    latest_end = min(latest_end or planning_end, planning_end)
    earliest_start = max(planning_start, get_paid_leave_available_from(employee))
    max_chargeable_days = max_chargeable_days or Decimal(target_days)
    yielded_count = 0

    for item in sorted(current_items or [], key=lambda candidate: (candidate.end_date, candidate.start_date, candidate.id or 0)):
        adjacent_periods = []

        after_start = item.end_date + timedelta(days=1)
        after_end = _end_date_for_chargeable_days(after_start, target_days, latest_end)
        if after_end is not None:
            adjacent_periods.append((after_start, after_end, {item.id}))

        before_end = min(item.start_date - timedelta(days=1), latest_end)
        before_start = _start_date_for_chargeable_days(before_end, target_days, earliest_start)
        if before_start is not None:
            adjacent_periods.append((before_start, before_end, {item.id}))

        for start_date, end_date, adjacent_ids in adjacent_periods:
            merged_start = min(start_date, item.start_date)
            merged_end = max(end_date, item.end_date)
            if (merged_end - merged_start).days + 1 < MIN_CONTINUOUS_PAID_LEAVE_DAYS:
                continue
            if _has_short_gap_to_employee_placement(
                placements,
                employee.id,
                start_date,
                end_date,
                exclude_item_ids=adjacent_ids,
            ):
                continue
            assessment = assess_schedule_draft_candidate(
                employee,
                start_date,
                end_date,
                year,
                placements,
                max_chargeable_days=max_chargeable_days,
                exclude_schedule_item_ids=exclude_schedule_item_ids,
            )
            if assessment["can_place"]:
                yield {
                    "start_date": start_date,
                    "end_date": end_date,
                    "assessment": assessment,
                    "target_days": Decimal(target_days),
                }
                yielded_count += 1
                if limit is not None and yielded_count >= limit:
                    return


def _find_adjacent_topup_candidate(employee, year, placements, current_items, target_days, latest_end, *, max_chargeable_days=None):
    for candidate in _iter_adjacent_topup_candidate_payloads(
        employee,
        year,
        placements,
        current_items,
        target_days,
        latest_end,
        max_chargeable_days=max_chargeable_days,
        limit=1,
    ):
        return candidate
    return None


def _auto_candidate_payload(candidate, comment):
    if candidate is None:
        return None
    return {
        "candidate": candidate,
        "comment": comment,
    }


def _find_auto_candidate_for_planning_need(employee, year, placements, current_items, planning_need):
    if not planning_need["needs_manual_attention"]:
        return None

    _, planning_end = _planning_year_bounds(year)
    open_required_days = planning_need["open_required_days"]
    if open_required_days <= 0:
        return None

    if planning_need["has_blocker"]:
        previous_year_closure = detect_previous_year_closure_need(employee, year, planning_need)
        previous_year_closure_days = quantize_leave_days(
            previous_year_closure["required_days"] if previous_year_closure else Decimal("0.00")
        )
        current_year_blocking_days = quantize_leave_days(
            max(planning_need["blocking_days"] - previous_year_closure_days, Decimal("0.00"))
        )
        if current_year_blocking_days > 0:
            target_before_deadline = quantize_leave_days(
                max(open_required_days - previous_year_closure_days, current_year_blocking_days)
            )
            candidate = _find_auto_candidate_for_need(
                employee,
                year,
                placements,
                target_before_deadline,
                planning_need["nearest_deadline"],
                urgent=True,
                allow_short_parts=False,
            )
            if candidate is not None:
                return _auto_candidate_payload(
                    candidate,
                    "Автоматически распределено: срочный остаток отпуска до срока.",
                )

            candidate = _find_adjacent_topup_candidate(
                employee,
                year,
                placements,
                current_items,
                current_year_blocking_days,
                planning_need["nearest_deadline"],
                max_chargeable_days=open_required_days,
            )
            if candidate is not None:
                return _auto_candidate_payload(
                    candidate,
                    "Автоматически продлено: срочный остаток закрыт соседней частью отпуска.",
                )

            candidate = _find_auto_candidate_for_need(
                employee,
                year,
                placements,
                current_year_blocking_days,
                planning_need["nearest_deadline"],
                urgent=True,
                allow_short_parts=True,
            )
            if candidate is not None:
                return _auto_candidate_payload(
                    candidate,
                    "Автоматически распределено: короткий срочный остаток до срока.",
                )
            if planning_need["annual_remaining_days"] > 0:
                if planning_need["annual_remaining_days"] < MIN_CONTINUOUS_PAID_LEAVE_DAYS:
                    candidate = _find_adjacent_topup_candidate(
                        employee,
                        year,
                        placements,
                        current_items,
                        planning_need["annual_remaining_days"],
                        planning_end,
                        max_chargeable_days=open_required_days,
                    )
                    if candidate is not None:
                        return _auto_candidate_payload(
                        candidate,
                        "Автоматически продлено: автодобор выполнен, срочный остаток остался на ручную проверку.",
                    )
                candidate = _find_auto_candidate_for_need(
                    employee,
                    year,
                    placements,
                    planning_need["annual_remaining_days"],
                    planning_end,
                    urgent=False,
                    allow_short_parts=False,
                )
                if candidate is not None:
                    return _auto_candidate_payload(
                    candidate,
                    "Автоматически распределено: автодобор выполнен, срочный остаток остался на ручную проверку.",
                )
            return None

        target_after_previous_year_closure = quantize_leave_days(
            max(open_required_days - previous_year_closure_days, Decimal("0.00"))
        )
        if target_after_previous_year_closure <= 0:
            return None
        candidate = _find_auto_candidate_for_need(
            employee,
            year,
            placements,
            target_after_previous_year_closure,
            planning_end,
            urgent=False,
            allow_short_parts=False,
        )
        return _auto_candidate_payload(
            candidate,
            "Автоматически распределено: автодобор при отдельном срочном остатке.",
        )

    if open_required_days < MIN_CONTINUOUS_PAID_LEAVE_DAYS:
        candidate = _find_adjacent_topup_candidate(
            employee,
            year,
            placements,
            current_items,
            open_required_days,
            planning_end,
            max_chargeable_days=open_required_days,
        )
        if candidate is not None:
            return _auto_candidate_payload(
                candidate,
                "Автоматически продлено: короткий остаток объединен с соседним отпуском.",
            )

    candidate = _find_auto_candidate_for_need(
        employee,
        year,
        placements,
        open_required_days,
        planning_end,
        urgent=False,
        allow_short_parts=False,
    )
    return _auto_candidate_payload(
        candidate,
        "Автоматически распределено: добивка по пожеланию сотрудника.",
    )


def _sort_auto_place_employees(employees, planning_need_by_employee):
    def sort_key(employee):
        planning_need = planning_need_by_employee[employee.id]
        nearest_deadline = planning_need["nearest_deadline"] or date.max
        return (
            0 if planning_need["has_blocker"] else 1,
            nearest_deadline,
            -float(planning_need["blocking_days"]),
            -float(planning_need["open_required_days"]),
            employee.last_name,
            employee.first_name,
            employee.id,
        )

    return sorted(
        [
            employee
            for employee in employees
            if planning_need_by_employee[employee.id]["needs_manual_attention"]
        ],
        key=sort_key,
    )


def _auto_candidate_packages_for_employee(context, employee, *, package_limit=AUTO_DRAFT_MAX_PACKAGE_SUGGESTIONS):
    planning_need = _current_employee_planning_need(context, employee)
    target = _auto_place_target_for_planning_need(employee, context.year, planning_need)
    if target is None:
        return [], None

    packages = []
    seen = set()
    for package in _manual_candidate_packages(
        context,
        employee,
        limit=package_limit,
    ):
        package = _trim_auto_candidate_package_to_target(package, target["target_days"])
        key = _manual_package_key(package)
        if not key or key in seen:
            continue
        seen.add(key)
        packages.append(package)

    packages = _rank_auto_candidate_packages(packages)
    for package in packages:
        package.metadata.update(
            {
                "package_kind": "auto_place_package",
                "auto_place_package": True,
                "auto_place_target_days": target["target_days"],
            }
        )
        for candidate in package.candidates:
            if candidate.metadata.get("is_preference_candidate"):
                candidate.metadata["auto_place_preference_seed"] = True
            if candidate.comment.startswith("Предложение модуля"):
                candidate.comment = "Автоматически распределено: выбран лучший пакет периодов."
    selected_package = next(
        (
            package
            for package in packages
            if package.candidates and all(_candidate_passed_hard_rules(candidate) for candidate in package.candidates)
        ),
        None,
    )
    return packages, selected_package


def _trim_auto_candidate_package_to_target(package, target_days):
    target_days = _feature_decimal(target_days)
    if target_days <= 0:
        return package

    selected_candidates = []
    total_days = Decimal("0.00")
    for candidate in package.candidates:
        selected_candidates.append(candidate)
        total_days += _feature_decimal(
            candidate.metadata.get("chargeable_days")
            or (candidate.assessment or {}).get("chargeable_days")
        )
        if total_days >= target_days:
            break

    remaining_days = quantize_leave_days(max(target_days - total_days, Decimal("0.00")))
    if len(selected_candidates) == len(package.candidates):
        package.metadata.update(
            {
                "auto_place_target_days": target_days,
                "remaining_after_package": remaining_days,
                "package_closes_need": remaining_days <= 0,
            }
        )
        return package

    return DraftGenerationCandidatePackage(
        employee=package.employee,
        candidates=selected_candidates,
        source=package.source,
        explanation=(
            "Пакет полностью закрывает автоматическую цель."
            if remaining_days <= 0
            else "Пакет закрывает часть автоматической цели."
        ),
        metadata={
            **(package.metadata or {}),
            "total_chargeable_days": total_days,
            "periods_count": len(selected_candidates),
            "remaining_after_package": remaining_days,
            "package_closes_need": remaining_days <= 0,
            "auto_place_target_days": target_days,
        },
    )


def _rank_auto_candidate_packages(packages):
    def package_rank(package):
        candidates = package.candidates
        total_days = sum((_feature_decimal(candidate.metadata.get("chargeable_days")) for candidate in candidates), Decimal("0.00"))
        max_risk = max((int(candidate.metadata.get("risk_score") or 0) for candidate in candidates), default=0)
        closes_need = bool(package.metadata.get("package_closes_need"))
        extends_existing = any(candidate.metadata.get("extends_existing_item") for candidate in candidates)
        target_days = _feature_decimal(package.metadata.get("auto_place_target_days"))
        target_is_short = Decimal("0.00") < target_days < Decimal(MIN_CONTINUOUS_PAID_LEAVE_DAYS)
        has_partial_preference = any(str(candidate.metadata.get("preference_match") or "").endswith("_partial") for candidate in candidates)
        has_exact_preference = any(
            candidate.metadata.get("preference_match") in {"primary", "backup"}
            for candidate in candidates
        )
        single_period = len(candidates) == 1
        return (
            1 if closes_need else 0,
            1 if extends_existing else 0,
            1 if has_exact_preference else 0,
            1 if single_period and not (target_is_short and has_partial_preference) else 0,
            _manual_package_quality_score(package),
            total_days,
            Decimal("100.00") - Decimal(max_risk),
            -len(candidates),
        )

    return sorted(packages, key=package_rank, reverse=True)


def _register_virtual_candidate_package(context, package):
    for candidate in package.candidates:
        chargeable_days = (
            candidate.metadata.get("chargeable_days")
            or (candidate.assessment or {}).get("chargeable_days")
            or 0
        )
        virtual_item = _virtual_draft_item(
            candidate.employee,
            candidate.start_date,
            candidate.end_date,
            chargeable_days,
            source=candidate.source,
            selected_candidate=candidate,
        )
        _register_draft_item_in_generation_context(context, virtual_item)
    context.planning_need_by_employee[package.employee.id] = _current_employee_planning_need(context, package.employee)


def _persist_auto_candidate_packages(generation_run, schedule, packages, selected_package):
    selected_key = _manual_package_key(selected_package)
    selected_record, selected_candidate_records, selected_period_records = _persist_manual_candidate_package(
        generation_run,
        schedule,
        selected_package,
        decision=VacationScheduleCandidatePackage.DECISION_SELECTED,
        decision_rank=1,
    )

    rejected_rank = 2
    for package in packages[:AUTO_DRAFT_PERSISTED_PACKAGE_ALTERNATIVES]:
        if _manual_package_key(package) == selected_key:
            continue
        _persist_manual_candidate_package(
            generation_run,
            schedule,
            package,
            decision=VacationScheduleCandidatePackage.DECISION_REJECTED,
            decision_rank=rejected_rank,
        )
        rejected_rank += 1

    return selected_record, selected_candidate_records, selected_period_records


def _link_package_periods_to_draft_items(period_records, items):
    for period_record in period_records:
        schedule_item = _find_covering_draft_item(items, period_record.start_date, period_record.end_date)
        if schedule_item is None:
            continue
        period_record.schedule_item = schedule_item
        period_record.save(update_fields=["schedule_item"])


def _create_draft_items_from_candidate_package(
    schedule,
    context,
    employee,
    package,
    *,
    generation_run,
    selected_candidate_records,
    selected_period_records,
):
    created_items = []
    for candidate, selected_candidate_record in zip(package.candidates, selected_candidate_records):
        if not _candidate_passed_hard_rules(candidate):
            continue
        item = _create_draft_item_from_generation_candidate(
            schedule,
            candidate,
            generation_run=generation_run,
            selected_candidate_record=selected_candidate_record,
        )
        _register_draft_item_in_generation_context(context, item)
        created_items.append(item)

    _merge_adjacent_employee_draft_items(
        schedule,
        employee,
        context.draft_items_by_employee,
        context.placements,
    )
    refreshed_items = list(
        VacationScheduleItem.objects.filter(
            schedule=schedule,
            employee=employee,
            status=VacationScheduleItem.STATUS_DRAFT,
        ).order_by("start_date", "end_date", "id")
    )
    _link_package_periods_to_draft_items(selected_period_records, refreshed_items)
    context.planning_need_by_employee[employee.id] = _current_employee_planning_need(context, employee)
    return created_items


def _auto_place_target_for_planning_need(employee, year, planning_need):
    if not planning_need["needs_manual_attention"]:
        return None

    _, planning_end = _planning_year_bounds(year)
    if planning_need["has_blocker"]:
        previous_year_closure = detect_previous_year_closure_need(employee, year, planning_need)
        previous_year_closure_days = quantize_leave_days(
            previous_year_closure["required_days"] if previous_year_closure else Decimal("0.00")
        )
        current_year_blocking_days = quantize_leave_days(
            max(planning_need["blocking_days"] - previous_year_closure_days, Decimal("0.00"))
        )
        if current_year_blocking_days > 0:
            return {
                "target_days": current_year_blocking_days,
                "latest_end": planning_need["nearest_deadline"],
                "urgent": True,
                "allow_short_parts": False,
                "comment": "Автоматически распределено: срочный остаток отпуска.",
            }

        current_year_target_days = quantize_leave_days(
            max(planning_need["open_required_days"] - previous_year_closure_days, Decimal("0.00"))
        )
        if current_year_target_days <= 0:
            return None

        return {
            "target_days": current_year_target_days,
            "latest_end": planning_end,
            "urgent": False,
            "allow_short_parts": False,
            "comment": "Автоматически распределено: автодобор при отдельном срочном остатке.",
        }

    return {
        "target_days": planning_need["open_required_days"],
        "latest_end": planning_end,
        "urgent": False,
        "allow_short_parts": False,
        "comment": "Автоматически распределено: добивка по пожеланию сотрудника.",
    }


def _count_manual_draft_tasks_from_context(context):
    employee_ids = [employee.id for employee in context.eligible_employees]
    active_urgent_closure_by_employee = get_active_urgent_closure_payload_map(employee_ids, context.year)
    manual_count = 0
    for employee in context.eligible_employees:
        planning_need = _current_employee_planning_need(context, employee)
        context.planning_need_by_employee[employee.id] = planning_need
        if planning_need["needs_manual_attention"] or active_urgent_closure_by_employee.get(employee.id) is not None:
            manual_count += 1
    return manual_count


def _should_repeat_auto_place_pass(*, placed_count, removed_conflicts, unresolved_count, pass_index, has_placeable_remainder=False):
    return (
        unresolved_count > 0
        and pass_index < AUTO_DRAFT_MAX_AUTO_PLACE_PASSES
        and (placed_count > 0 or removed_conflicts > 0 or has_placeable_remainder)
    )


def _has_placeable_non_blocking_auto_place_remainder(context):
    for employee in _sort_auto_place_employees(context.eligible_employees, context.planning_need_by_employee):
        planning_need = _current_employee_planning_need(context, employee)
        context.planning_need_by_employee[employee.id] = planning_need
        if planning_need.get("has_blocker"):
            continue
        _, selected_package = _auto_candidate_packages_for_employee(context, employee, package_limit=3)
        if selected_package is not None:
            return True
    return False


@transaction.atomic
def create_schedule_draft_from_preferences(*, year, actor):
    if not is_active_planning_year(year):
        raise ValidationError("Черновик можно создать только для активного планового года.")

    collection = VacationPreferenceCollection.objects.select_for_update().filter(year=year).first()
    if collection is None:
        raise ValidationError("Сбор пожеланий за этот год не найден.")
    if collection.status != VacationPreferenceCollection.STATUS_FINISHED:
        raise ValidationError("Черновик можно создать только после завершения сбора пожеланий.")

    existing_schedule = VacationSchedule.objects.select_for_update().filter(year=year).first()
    if existing_schedule is not None:
        if existing_schedule.status == VacationSchedule.STATUS_DRAFT:
            return {
                "schedule": existing_schedule,
                "created": False,
                "placed_count": existing_schedule.items.filter(status=VacationScheduleItem.STATUS_DRAFT).count(),
            }
        raise ValidationError("Для этого года уже есть утвержденный или согласуемый график.")

    schedule = VacationSchedule.objects.create(
        year=year,
        status=VacationSchedule.STATUS_DRAFT,
        created_by=actor,
        generated_at=timezone.now(),
    )
    context = _build_draft_generation_context(year, schedule)
    generation_run = _start_schedule_generation_run(schedule, actor)
    placed_count = 0

    for employee in context.eligible_employees:
        if context.preference_state_by_employee.get(employee.id) != VacationPreference.STATUS_FILLED:
            continue

        candidates = _rank_generation_candidates(_build_preference_generation_candidates(context, employee))
        selected_candidate = _select_preference_generation_candidate_from_ranked(candidates)
        candidates = _selected_candidate_first(candidates, selected_candidate)
        selected_candidate_record = _persist_generation_candidates(
            generation_run,
            schedule,
            candidates,
            selected_candidate=selected_candidate,
        )
        if selected_candidate is None:
            continue

        item = _create_draft_item_from_generation_candidate(
            schedule,
            selected_candidate,
            generation_run=generation_run,
            selected_candidate_record=selected_candidate_record,
        )
        _register_draft_item_in_generation_context(context, item)
        placed_count += 1

    removed_conflicts = _remove_conflicting_generated_draft_items(schedule)
    if removed_conflicts:
        context = _build_draft_generation_context(year, schedule)
    manual_count = _count_manual_draft_tasks_from_context(context)
    _finish_schedule_generation_run(generation_run, manual_count=manual_count)

    return {
        "schedule": schedule,
        "created": True,
        "placed_count": max(placed_count - removed_conflicts, 0),
    }


@transaction.atomic
def auto_place_remaining_schedule_draft(
    *,
    year,
    actor,
    _pass_index=1,
    _generation_run=None,
    progress_callback=None,
    use_package_selection=False,
):
    schedule = VacationSchedule.objects.select_for_update().filter(
        year=year,
        status=VacationSchedule.STATUS_DRAFT,
    ).first()
    if schedule is None:
        raise ValidationError("Черновик графика за этот год не найден.")

    context = _build_draft_generation_context(year, schedule)
    owns_generation_run = _generation_run is None
    generation_run = _generation_run or _start_schedule_generation_run(schedule, actor)
    placed_count = 0
    unresolved_count = 0
    auto_employees = _sort_auto_place_employees(context.eligible_employees, context.planning_need_by_employee)
    total_employees = len(auto_employees)

    for processed_index, employee in enumerate(auto_employees, start=1):
        chunks_count = 0
        while chunks_count < AUTO_DRAFT_MAX_CHUNKS_PER_EMPLOYEE:
            current_items = context.draft_items_by_employee.get(employee.id, [])
            planning_need = _current_employee_planning_need(context, employee)
            if not planning_need["needs_manual_attention"]:
                context.planning_need_by_employee[employee.id] = planning_need
                break

            if use_package_selection:
                packages, selected_package = _auto_candidate_packages_for_employee(context, employee)
                if selected_package is None:
                    unresolved_count += 1
                    context.planning_need_by_employee[employee.id] = planning_need
                    break

                _, selected_candidate_records, selected_period_records = _persist_auto_candidate_packages(
                    generation_run,
                    schedule,
                    packages,
                    selected_package,
                )
                created_items = _create_draft_items_from_candidate_package(
                    schedule,
                    context,
                    employee,
                    selected_package,
                    generation_run=generation_run,
                    selected_candidate_records=selected_candidate_records,
                    selected_period_records=selected_period_records,
                )
                placed_periods = len(created_items)
                if placed_periods <= 0:
                    unresolved_count += 1
                    break
                placed_count += placed_periods
                chunks_count += placed_periods
            else:
                candidates = _rank_auto_generation_candidates(
                    _build_auto_generation_candidates(
                        context,
                        employee,
                        current_items,
                        planning_need,
                    )
                )
                selected_candidate = _select_first_passed_generation_candidate(candidates)
                selected_candidate_record = _persist_generation_candidates(
                    generation_run,
                    schedule,
                    candidates,
                    selected_candidate=selected_candidate,
                )
                if selected_candidate is None:
                    unresolved_count += 1
                    context.planning_need_by_employee[employee.id] = planning_need
                    break

                item = _create_draft_item_from_generation_candidate(
                    schedule,
                    selected_candidate,
                    generation_run=generation_run,
                    selected_candidate_record=selected_candidate_record,
                )
                _register_draft_item_in_generation_context(context, item)
                _merge_adjacent_employee_draft_items(
                    schedule,
                    employee,
                    context.draft_items_by_employee,
                    context.placements,
                )
                placed_count += 1
                chunks_count += 1

        if chunks_count >= AUTO_DRAFT_MAX_CHUNKS_PER_EMPLOYEE:
            planning_need = _current_employee_planning_need(context, employee)
            if planning_need["needs_manual_attention"]:
                unresolved_count += 1

        if progress_callback is not None:
            progress_callback(
                {
                    "processed": processed_index,
                    "total": total_employees,
                    "employee_id": employee.id,
                    "employee_name": employee.full_name,
                    "placed_count": placed_count,
                    "unresolved_count": unresolved_count,
                }
            )

    removed_conflicts = _remove_conflicting_generated_draft_items(schedule)
    placed_count = max(placed_count - removed_conflicts, 0)
    unresolved_count = build_schedule_draft_page_context(year)["draft_summary"]["manual"]
    has_placeable_remainder = False
    if unresolved_count > 0:
        has_placeable_remainder = _has_placeable_non_blocking_auto_place_remainder(
            _build_draft_generation_context(year, schedule)
        )
    if _should_repeat_auto_place_pass(
        placed_count=placed_count,
        removed_conflicts=removed_conflicts,
        unresolved_count=unresolved_count,
        pass_index=_pass_index,
        has_placeable_remainder=has_placeable_remainder,
    ):
        follow_up_result = auto_place_remaining_schedule_draft(
            year=year,
            actor=actor,
            _pass_index=_pass_index + 1,
            _generation_run=generation_run,
            progress_callback=progress_callback,
            use_package_selection=use_package_selection,
        )
        placed_count += follow_up_result["placed_count"]
        unresolved_count = follow_up_result["unresolved_count"]

    if owns_generation_run:
        _finish_schedule_generation_run(generation_run, manual_count=unresolved_count)
        _invalidate_schedule_draft_manual_suggestion_cache(schedule)

    return {
        "schedule": schedule,
        "placed_count": placed_count,
        "unresolved_count": unresolved_count,
    }
