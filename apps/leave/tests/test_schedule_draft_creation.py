import json
from datetime import date, timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.accounts.services import sync_employee_user
from apps.core.models import Notification
from apps.employees.models import Employees
from apps.leave.models import (
    DepartmentWorkload,
    VacationPreference,
    VacationPreferenceCollection,
    VacationSchedule,
    VacationScheduleCandidate,
    VacationScheduleCandidateFeedback,
    VacationScheduleCandidatePackage,
    VacationScheduleCandidatePackagePeriod,
    VacationScheduleGenerationRun,
    VacationScheduleDepartmentApproval,
    VacationScheduleItem,
    VacationScheduleManualSuggestionCache,
    VacationUrgentClosureRequest,
)
from apps.leave.services.dates import add_months_safe, get_chargeable_leave_days
from apps.leave.services.preferences import (
    build_preference_collection_summary,
    get_employee_preference_pair_map,
    get_employee_preference_state_map,
    preference_readiness_url,
)
from apps.leave.services.schedule_drafts import (
    _build_employee_schedule_planning_need_from_rows,
    _build_auto_generation_candidates,
    _build_draft_generation_context,
    _build_preference_generation_candidates,
    auto_place_remaining_schedule_draft,
    build_manual_schedule_draft_preview,
    build_schedule_draft_auto_place_preview,
    place_manual_schedule_draft_items,
)
from apps.leave.services.schedule_planning import schedule_planning_url
from apps.leave.services.candidate_scoring import ACTIVE_CANDIDATE_SCORER_VERSION
from apps.leave.tests.base import LeaveTestCase


class ScheduleDraftCreationTests(LeaveTestCase):
    def test_hr_creates_schedule_draft_from_finished_collection(self):
        year = self._year()
        self.activate_only(self.employee, self.hr_employee)
        self._set_filled_preferences(
            self.employee,
            primary_start=date(year, 6, 1),
            primary_end=date(year, 6, 14),
            backup_start=date(year, 9, 1),
            backup_end=date(year, 9, 14),
        )
        self.finish_preference_collection(year)
        self.client.force_login(self.hr_employee.user)

        response = self.client.post(reverse("schedule_draft_create", args=[year]))

        self.assertRedirects(response, reverse("schedule_draft_detail", args=[year]))
        schedule = VacationSchedule.objects.get(year=year)
        self.assertEqual(schedule.status, VacationSchedule.STATUS_DRAFT)
        item = VacationScheduleItem.objects.get(schedule=schedule, employee=self.employee)
        self.assertEqual(item.status, VacationScheduleItem.STATUS_DRAFT)
        self.assertEqual(item.source, VacationScheduleItem.SOURCE_GENERATED)
        self.assertEqual(item.start_date, date(year, 6, 1))
        self.assertTrue(item.generated_by_ai)
        self.assertIsNotNone(item.ai_score)
        self.assertIsNotNone(item.ai_confidence)
        self.assertFalse(VacationScheduleManualSuggestionCache.objects.filter(schedule=schedule).exists())

        readiness_response = self.client.get(reverse("preference_collection_readiness", args=[year]))
        self.assertContains(readiness_response, "Открыть черновик")

    def test_schedule_draft_creation_is_idempotent(self):
        year = self._year()
        self.activate_only(self.employee, self.hr_employee)
        self._set_filled_preferences(
            self.employee,
            primary_start=date(year, 6, 1),
            primary_end=date(year, 6, 14),
            backup_start=date(year, 9, 1),
            backup_end=date(year, 9, 14),
        )
        self.finish_preference_collection(year)
        self.client.force_login(self.hr_employee.user)

        self.client.post(reverse("schedule_draft_create", args=[year]))
        self.client.post(reverse("schedule_draft_create", args=[year]))

        self.assertEqual(VacationSchedule.objects.filter(year=year).count(), 1)
        self.assertEqual(VacationScheduleItem.objects.filter(schedule__year=year, employee=self.employee).count(), 1)

    def test_schedule_draft_prepares_primary_and_backup_generation_candidates(self):
        year = self._year()
        self._set_filled_preferences(
            self.employee,
            primary_start=date(year, 6, 1),
            primary_end=date(year, 6, 14),
            backup_start=date(year, 9, 1),
            backup_end=date(year, 9, 14),
        )
        schedule = VacationSchedule.objects.create(
            year=year,
            status=VacationSchedule.STATUS_DRAFT,
            created_by=self.hr_employee,
        )
        context = _build_draft_generation_context(year, schedule)

        candidates = _build_preference_generation_candidates(context, self.employee)

        self.assertEqual([candidate.kind for candidate in candidates], ["primary_preference", "backup_preference"])
        self.assertEqual(candidates[0].start_date, date(year, 6, 1))
        self.assertEqual(candidates[1].start_date, date(year, 9, 1))
        self.assertTrue(all(candidate.assessment is not None for candidate in candidates))
        self.assertTrue(candidates[0].assessment["can_place"])
        self.assertTrue(all("passed_hard_rules" in candidate.metadata for candidate in candidates))
        self.assertTrue(candidates[0].metadata["passed_hard_rules"])
        self.assertEqual(candidates[0].metadata["block_reason_key"], "")

    def test_schedule_draft_marks_blocked_preference_generation_candidate(self):
        year = self._year()
        self._set_filled_preferences(
            self.employee,
            primary_start=date(year, 6, 1),
            primary_end=date(year, 6, 14),
            backup_start=date(year, 9, 1),
            backup_end=date(year, 9, 14),
        )
        schedule = VacationSchedule.objects.create(
            year=year,
            status=VacationSchedule.STATUS_DRAFT,
            created_by=self.hr_employee,
        )
        VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(year, 6, 1),
            end_date=date(year, 6, 14),
            vacation_type="paid",
            chargeable_days=get_chargeable_leave_days(date(year, 6, 1), date(year, 6, 14), "paid"),
            status=VacationScheduleItem.STATUS_DRAFT,
            source=VacationScheduleItem.SOURCE_GENERATED,
            risk_score=0,
            risk_level=VacationScheduleItem.RISK_LOW,
        )
        context = _build_draft_generation_context(year, schedule)

        candidates = _build_preference_generation_candidates(context, self.employee)
        primary_candidate = candidates[0]

        self.assertFalse(primary_candidate.metadata["passed_hard_rules"])
        self.assertEqual(primary_candidate.metadata["block_reason_key"], "employee_overlap")
        self.assertIn("уже есть отпуск", primary_candidate.metadata["block_reason"])
        self.assertFalse(primary_candidate.assessment["can_place"])

    def test_schedule_draft_persists_preference_generation_run_and_candidates(self):
        year = self._year()
        self.activate_only(self.employee, self.hr_employee)
        self._set_filled_preferences(
            self.employee,
            primary_start=date(year, 6, 1),
            primary_end=date(year, 6, 14),
            backup_start=date(year, 9, 1),
            backup_end=date(year, 9, 14),
        )
        self.finish_preference_collection(year)
        self.client.force_login(self.hr_employee.user)

        self.client.post(reverse("schedule_draft_create", args=[year]))

        schedule = VacationSchedule.objects.get(year=year)
        generation_run = schedule.generation_runs.get()
        self.assertEqual(generation_run.mode, VacationScheduleGenerationRun.MODE_HYBRID)
        self.assertEqual(generation_run.status, VacationScheduleGenerationRun.STATUS_COMPLETED)
        self.assertEqual(generation_run.model_version, ACTIVE_CANDIDATE_SCORER_VERSION)
        self.assertEqual(generation_run.candidates_count, 2)
        self.assertEqual(generation_run.selected_count, 1)
        self.assertEqual(generation_run.rejected_count, 1)
        self.assertIsNotNone(generation_run.average_score)

        selected_candidate = generation_run.candidates.get(decision=VacationScheduleCandidate.DECISION_SELECTED)
        rejected_candidate = generation_run.candidates.get(decision=VacationScheduleCandidate.DECISION_REJECTED)
        item = VacationScheduleItem.objects.get(schedule=schedule, employee=self.employee)
        self.assertEqual(selected_candidate.kind, VacationScheduleCandidate.KIND_PRIMARY_PREFERENCE)
        self.assertEqual(rejected_candidate.kind, VacationScheduleCandidate.KIND_BACKUP_PREFERENCE)
        self.assertIsNotNone(selected_candidate.score)
        self.assertIsNotNone(selected_candidate.confidence)
        self.assertEqual(selected_candidate.model_version, ACTIVE_CANDIDATE_SCORER_VERSION)
        self.assertIn("Нейромодуль", selected_candidate.explanation)
        self.assertIn("Оценка", selected_candidate.explanation)
        self.assertIsNotNone(rejected_candidate.score)
        self.assertEqual(rejected_candidate.model_version, ACTIVE_CANDIDATE_SCORER_VERSION)
        self.assertEqual(item.generation_run_id, generation_run.id)
        self.assertEqual(item.selected_candidate_id, selected_candidate.id)
        self.assertTrue(item.generated_by_ai)
        self.assertEqual(item.ai_score, selected_candidate.score)
        self.assertEqual(item.ai_confidence, selected_candidate.confidence)
        self.assertEqual(item.ai_model_version, ACTIVE_CANDIDATE_SCORER_VERSION)
        self.assertEqual(item.ai_explanation, selected_candidate.explanation)
        detail_response = self.client.get(reverse("schedule_draft_detail", args=[year]))
        placed_row = detail_response.context["placed_rows"][0]
        self.assertIsNotNone(placed_row["ai_decision"])
        self.assertEqual(placed_row["ai_decision"]["score"], selected_candidate.score)
        self.assertEqual(placed_row["ai_decision"]["confidence"], selected_candidate.confidence)
        self.assertContains(detail_response, "Оценка модуля")
        self.assertContains(detail_response, "Уверенность")
        review_response = self.client.get(reverse("schedule_draft_item_review", args=[year, item.id]))
        self.assertIn(selected_candidate.explanation, review_response.json()["html"])
        features = selected_candidate.features
        self.assertTrue(features["passed_hard_rules"])
        self.assertEqual(features["feature_schema_version"], 1)
        self.assertEqual(features["candidate_kind"], VacationScheduleCandidate.KIND_PRIMARY_PREFERENCE)
        self.assertEqual(features["employee_role"], self.employee.role)
        self.assertGreater(features["employee_tenure_days_at_year_end"], 0)
        self.assertEqual(features["period_start_month"], 6)
        self.assertGreater(features["period_chargeable_days"], 0)
        self.assertGreater(features["planning_open_required_days"], 0)
        self.assertGreater(features["planning_candidate_coverage_ratio"], 0)
        self.assertTrue(features["preference_has_preference"])
        self.assertEqual(features["preference_priority"], VacationPreference.PRIORITY_PRIMARY)
        self.assertTrue(features["preference_exact_period_match"])
        self.assertGreaterEqual(features["risk_department_load_level"], 1)
        self.assertIn("risk_staff_margin", features)
        self.assertIn(features["scoring_recommendation"], ["prefer", "normal", "avoid"])
        self.assertEqual(features["scoring_scorer_kind"], "tabular_mlp")

    def test_schedule_draft_hybrid_selects_higher_scored_backup_candidate(self):
        year = self._year()
        self.activate_only(self.employee, self.department_head, self.hr_employee)
        self._set_filled_preferences(
            self.employee,
            primary_start=date(year, 6, 1),
            primary_end=date(year, 6, 14),
            backup_start=date(year, 9, 1),
            backup_end=date(year, 9, 14),
        )
        DepartmentWorkload.objects.update_or_create(
            department=self.employee.department,
            year=year,
            month=6,
            defaults={"load_level": 5, "min_staff_required": 1, "max_absent": 10},
        )
        DepartmentWorkload.objects.update_or_create(
            department=self.employee.department,
            year=year,
            month=9,
            defaults={"load_level": 1, "min_staff_required": 1, "max_absent": 10},
        )
        self.finish_preference_collection(year)
        self.client.force_login(self.hr_employee.user)

        self.client.post(reverse("schedule_draft_create", args=[year]))

        schedule = VacationSchedule.objects.get(year=year)
        generation_run = schedule.generation_runs.get()
        primary_candidate = generation_run.candidates.get(kind=VacationScheduleCandidate.KIND_PRIMARY_PREFERENCE)
        backup_candidate = generation_run.candidates.get(kind=VacationScheduleCandidate.KIND_BACKUP_PREFERENCE)
        selected_candidate = generation_run.candidates.get(decision=VacationScheduleCandidate.DECISION_SELECTED)
        item = VacationScheduleItem.objects.get(schedule=schedule, employee=self.employee)
        self.assertEqual(selected_candidate.id, backup_candidate.id)
        self.assertGreater(backup_candidate.score, primary_candidate.score)
        self.assertEqual(backup_candidate.decision_rank, 1)
        self.assertEqual(primary_candidate.decision, VacationScheduleCandidate.DECISION_REJECTED)
        self.assertEqual(item.start_date, date(year, 9, 1))
        self.assertEqual(item.selected_candidate_id, backup_candidate.id)

    def test_schedule_draft_detail_exposes_compact_card_context_and_calendar_link(self):
        year = self._year()
        self.employee.date_joined = self.today
        self.employee.save(update_fields=["date_joined"])
        self.activate_only(self.employee, self.hr_employee)
        self._set_filled_preferences(
            self.employee,
            primary_start=date(year, 6, 1),
            primary_end=date(year, 6, 14),
            backup_start=date(year, 9, 1),
            backup_end=date(year, 9, 14),
        )
        self.finish_preference_collection(year)
        self.client.force_login(self.hr_employee.user)
        self.client.post(reverse("schedule_draft_create", args=[year]))

        response = self.client.get(reverse("schedule_draft_detail", args=[year]))

        row = response.context["placed_rows"][0]
        self.assertIn("Назначено:", row["assigned_label"])
        self.assertIn("calendar_modal=employee_detail", row["calendar_url"])
        self.assertIn(f"calendar_employee={row['employee'].id}", row["calendar_url"])
        self.assertEqual(row["new_hire_badge"]["label"], "Новичок")
        self.assertContains(response, "Назначено")
        self.assertContains(response, "Показать на графике")
        self.assertContains(response, "data-draft-review-open")
        self.assertContains(response, 'class="new-hire-badge"')
        self.assertContains(response, "person_add")
        self.assertContains(response, "data-draft-day-calculation-open")
        self.assertContains(response, "Расчёт")
        self.assertNotContains(response, "Доступно к концу")

    def test_schedule_draft_item_review_endpoint_returns_candidates(self):
        year = self._year()
        self.activate_only(self.employee, self.hr_employee)
        self._set_filled_preferences(
            self.employee,
            primary_start=date(year, 6, 1),
            primary_end=date(year, 6, 14),
            backup_start=date(year, 9, 1),
            backup_end=date(year, 9, 14),
        )
        self.finish_preference_collection(year)
        self.client.force_login(self.hr_employee.user)
        self.client.post(reverse("schedule_draft_create", args=[year]))
        item = VacationScheduleItem.objects.get(schedule__year=year, employee=self.employee)

        response = self.client.get(reverse("schedule_draft_item_review", args=[year, item.id]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("Кандидаты", payload["html"])
        self.assertIn("Проверка", payload["html"])
        self.assertIn("Согласен", payload["html"])
        self.assertGreaterEqual(VacationScheduleCandidate.objects.filter(schedule=item.schedule, employee=self.employee).count(), 2)

    def test_schedule_draft_tries_backup_when_primary_has_staffing_conflict(self):
        year = self._year()
        self.activate_only(self.employee, self.department_head, self.hr_employee)
        self._set_filled_preferences(
            self.employee,
            primary_start=date(year, 6, 1),
            primary_end=date(year, 6, 14),
            backup_start=date(year, 9, 1),
            backup_end=date(year, 9, 14),
        )
        self._set_filled_preferences(
            self.department_head,
            primary_start=date(year, 6, 1),
            primary_end=date(year, 6, 14),
            backup_start=date(year, 10, 1),
            backup_end=date(year, 10, 14),
        )
        self.finish_preference_collection(year)
        self.client.force_login(self.hr_employee.user)

        self.client.post(reverse("schedule_draft_create", args=[year]))

        schedule = VacationSchedule.objects.get(year=year)
        employee_item = VacationScheduleItem.objects.get(schedule=schedule, employee=self.employee)
        head_item = VacationScheduleItem.objects.get(schedule=schedule, employee=self.department_head)
        self.assertEqual(employee_item.start_date, date(year, 6, 1))
        self.assertEqual(head_item.start_date, date(year, 10, 1))
        generation_run = schedule.generation_runs.get()
        self.assertEqual(generation_run.candidates_count, 4)
        self.assertEqual(generation_run.selected_count, 2)
        blocked_candidate = generation_run.candidates.get(
            employee=self.department_head,
            kind=VacationScheduleCandidate.KIND_PRIMARY_PREFERENCE,
        )
        selected_backup_candidate = generation_run.candidates.get(
            employee=self.department_head,
            kind=VacationScheduleCandidate.KIND_BACKUP_PREFERENCE,
        )
        self.assertEqual(blocked_candidate.decision, VacationScheduleCandidate.DECISION_BLOCKED)
        self.assertEqual(blocked_candidate.block_reason_key, "staffing_conflict")
        self.assertEqual(blocked_candidate.score, Decimal("0.00"))
        self.assertEqual(blocked_candidate.model_version, ACTIVE_CANDIDATE_SCORER_VERSION)
        self.assertIn("заблокирован", blocked_candidate.explanation.lower())
        blocked_features = blocked_candidate.features
        self.assertFalse(blocked_features["candidate_passed_hard_rules"])
        self.assertEqual(blocked_features["candidate_block_reason_key"], "staffing_conflict")
        self.assertTrue(blocked_features["risk_is_conflict"])
        self.assertGreaterEqual(blocked_features["risk_level_weight"], 1)
        self.assertEqual(blocked_features["scoring_recommendation"], "blocked")
        self.assertEqual(head_item.generation_run_id, generation_run.id)
        self.assertEqual(head_item.selected_candidate_id, selected_backup_candidate.id)

        response = self.client.get(reverse("schedule_draft_detail", args=[year]))
        self.assertContains(response, "schedule-draft-card__profile schedule-draft-card__profile--employee")
        self.assertContains(response, "schedule-draft-card__profile schedule-draft-card__profile--department-head")
        self.assertContains(
            response,
            "schedule-draft-card__management-badge schedule-draft-card__management-badge--department-head",
        )
        self.assertContains(response, "Руководитель отдела")
        self.assertNotContains(response, "schedule-draft-card--risk")

    def test_schedule_draft_day_calculation_endpoint_returns_plan_breakdown(self):
        year = self._year()
        self.activate_only(self.employee, self.hr_employee)
        self.employee.date_joined = date(year, 1, 1)
        self.employee.annual_paid_leave_days = 52
        self.employee.save(update_fields=["date_joined", "annual_paid_leave_days"])
        schedule = self.create_minimal_draft(year=year)
        self.create_employee_draft_item(
            self.employee,
            schedule=schedule,
            start_date=date(year, 7, 1),
            end_date=date(year, 7, 14),
        )
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("schedule_draft_day_calculation", args=[year, self.employee.id]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["annual_target_days"], 52)
        self.assertEqual(payload["target_days"], 52)
        self.assertEqual(payload["placed_days"], 14)
        self.assertEqual(payload["open_required_days"], 38)
        self.assertIn("reason_text", payload)
        self.assertGreaterEqual(len(payload["breakdown"]), 5)

    def test_schedule_draft_day_calculation_shows_mandatory_previous_year_deadline(self):
        year = self._year()
        self.activate_only(self.employee, self.hr_employee)
        self.employee.date_joined = date(year - 2, 1, 4)
        self.employee.annual_paid_leave_days = 52
        self.employee.save(update_fields=["date_joined", "annual_paid_leave_days"])
        self.create_minimal_draft(year=year)
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("schedule_draft_day_calculation", args=[year, self.employee.id]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertGreater(payload["mandatory_days"], 0)
        self.assertTrue(payload["nearest_deadline"])
        self.assertIn("обязательный остаток", payload["reason_text"].lower())

    def test_schedule_draft_day_calculation_access_rules(self):
        year = self._year()
        self.activate_only(self.employee, self.hr_employee, self.department_head, self.foreign_department_head)
        self.create_minimal_draft(year=year)
        url = reverse("schedule_draft_day_calculation", args=[year, self.employee.id])

        self.client.force_login(self.department_head.user)
        self.assertEqual(self.client.get(url).status_code, 200)

        self.client.force_login(self.foreign_department_head.user)
        self.assertEqual(self.client.get(url).status_code, 403)

        self.client.force_login(self.employee.user)
        self.assertEqual(self.client.get(url).status_code, 403)
