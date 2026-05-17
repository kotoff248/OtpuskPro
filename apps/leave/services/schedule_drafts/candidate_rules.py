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


def assess_schedule_draft_candidate(
    employee,
    start_date,
    end_date,
    year,
    placements,
    *,
    max_chargeable_days=None,
    exclude_schedule_item_id=None,
    exclude_schedule_item_ids=None,
    risk_context=None,
):
    if not start_date or not end_date:
        return {
            "can_place": False,
            "has_conflict": True,
            "reason": _manual_reason("missing_period", "Период не заполнен."),
        }
    if start_date.year != year or end_date.year != year or end_date < start_date:
        return {
            "can_place": False,
            "has_conflict": True,
            "reason": _manual_reason("invalid_period", "Период вне выбранного года."),
        }

    available_from = get_paid_leave_available_from(employee)
    if start_date < available_from:
        return {
            "can_place": False,
            "has_conflict": True,
            "reason": _manual_reason("too_early", f"Оплачиваемый отпуск доступен с {available_from:%d.%m.%Y}."),
        }

    chargeable_days = get_chargeable_leave_days(start_date, end_date, "paid")
    if chargeable_days <= 0:
        return {
            "can_place": False,
            "has_conflict": True,
            "reason": _manual_reason("empty_period", "В периоде нет списываемых дней отпуска."),
        }
    if max_chargeable_days is not None and Decimal(chargeable_days) > quantize_leave_days(max_chargeable_days):
        return {
            "can_place": False,
            "has_conflict": True,
            "reason": _manual_reason("too_many_days", "Период превышает остаток, который нужно распределить."),
        }

    if get_overlapping_requests(employee, start_date, end_date).exists():
        return {
            "can_place": False,
            "has_conflict": True,
            "reason": _manual_reason("employee_overlap", "У сотрудника уже есть активная заявка на эти даты."),
        }
    schedule_overlaps = get_overlapping_schedule_items(employee, start_date, end_date)
    if exclude_schedule_item_id is not None:
        schedule_overlaps = schedule_overlaps.exclude(pk=exclude_schedule_item_id)
    if exclude_schedule_item_ids:
        schedule_overlaps = schedule_overlaps.exclude(pk__in=list(exclude_schedule_item_ids))
    if schedule_overlaps.exists() or _has_employee_draft_overlap(
        placements,
        employee.id,
        start_date,
        end_date,
        exclude_item_id=exclude_schedule_item_id,
        exclude_item_ids=exclude_schedule_item_ids,
    ):
        return {
            "can_place": False,
            "has_conflict": True,
            "reason": _manual_reason("employee_overlap", "У сотрудника уже есть отпуск на эти даты."),
        }

    extra_absent_ids = _extra_absent_ids_for_period(
        placements,
        start_date,
        end_date,
        exclude_employee_id=employee.id,
    )
    risk_payload = calculate_vacation_request_risk_with_explanation(
        employee=employee,
        start_date=start_date,
        end_date=end_date,
        vacation_type="paid",
        exclude_schedule_item_id=exclude_schedule_item_id,
        exclude_schedule_item_ids=exclude_schedule_item_ids,
        extra_absent_employee_ids=extra_absent_ids,
        **(risk_context or {}),
    )
    explanation = risk_payload.get("risk_explanation") or {}
    has_conflict = bool(explanation.get("is_conflict"))
    if risk_payload.get("balance_after_request") is not None and risk_payload["balance_after_request"] < Decimal("0"):
        return {
            "can_place": False,
            "has_conflict": True,
            "risk_payload": risk_payload,
            "reason": _manual_reason("negative_balance", "Недостаточно оплачиваемых дней."),
        }
    if has_conflict:
        return {
            "can_place": False,
            "has_conflict": True,
            "risk_payload": risk_payload,
            "reason": _manual_reason(
                "staffing_conflict",
                explanation.get("short_reason") or "Период нарушает правила состава.",
            ),
        }

    return {
        "can_place": True,
        "has_conflict": False,
        "risk_payload": risk_payload,
        "chargeable_days": chargeable_days,
        "reason": _manual_reason("ok", "Период можно поставить в черновик."),
    }
