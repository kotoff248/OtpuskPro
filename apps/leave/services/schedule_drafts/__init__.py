from importlib import import_module

_MODULE_NAMES = (
    "constants",
    "types",
    "utils",
    "candidate_rules",
    "planning_need",
    "candidate_generation",
    "normalization",
    "auto_place",
    "manual",
    "department_rework",
    "page_context",
    "manual_suggestions",
)
_MODULES = [import_module(f"{__name__}.{module_name}") for module_name in _MODULE_NAMES]

from apps.leave.services.schedule_drafts.wiring import wire_modules

wire_modules(_MODULES)

from apps.leave.services.schedule_drafts.auto_place import auto_place_remaining_schedule_draft, create_schedule_draft_from_preferences
from apps.leave.services.schedule_drafts.candidate_rules import assess_schedule_draft_candidate
from apps.leave.services.schedule_drafts.department_rework import (
    build_schedule_department_rework_package_preview,
    build_schedule_department_rework_suggestions,
    get_schedule_department_rework_approval,
    replace_department_rework_employee_package,
)
from apps.leave.services.schedule_drafts.manual import (
    build_manual_schedule_draft_package_preview,
    place_manual_schedule_draft_item,
    place_manual_schedule_draft_items,
)
from apps.leave.services.schedule_drafts.manual_suggestions import (
    build_schedule_draft_auto_place_preview,
    build_schedule_draft_manual_suggestions,
    build_schedule_draft_urgent_closure_options,
)
from apps.leave.services.schedule_drafts.page_context import (
    build_manual_schedule_draft_preview,
    build_schedule_draft_item_review_context,
    build_schedule_draft_page_context,
    build_schedule_draft_summary_context,
    has_department_schedule_hard_conflicts,
)
from apps.leave.services.schedule_drafts.planning_need import (
    build_employee_schedule_planning_need,
    build_employee_schedule_planning_need_map,
    build_schedule_day_calculation_payload,
    build_schedule_draft_day_calculation,
)
from apps.leave.services.schedule_drafts.utils import get_schedule_draft_status, schedule_draft_create_url, schedule_draft_url

__all__ = [
    "assess_schedule_draft_candidate",
    "auto_place_remaining_schedule_draft",
    "build_employee_schedule_planning_need",
    "build_employee_schedule_planning_need_map",
    "build_manual_schedule_draft_package_preview",
    "build_manual_schedule_draft_preview",
    "build_schedule_day_calculation_payload",
    "build_schedule_department_rework_package_preview",
    "build_schedule_department_rework_suggestions",
    "build_schedule_draft_auto_place_preview",
    "build_schedule_draft_day_calculation",
    "build_schedule_draft_item_review_context",
    "build_schedule_draft_manual_suggestions",
    "build_schedule_draft_page_context",
    "build_schedule_draft_summary_context",
    "build_schedule_draft_urgent_closure_options",
    "create_schedule_draft_from_preferences",
    "get_schedule_department_rework_approval",
    "get_schedule_draft_status",
    "has_department_schedule_hard_conflicts",
    "place_manual_schedule_draft_item",
    "place_manual_schedule_draft_items",
    "replace_department_rework_employee_package",
    "schedule_draft_create_url",
    "schedule_draft_url",
]
