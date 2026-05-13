from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.leave.models import (
    VacationRequest,
    VacationSchedule,
    VacationScheduleCandidate,
    VacationScheduleGenerationRun,
    VacationScheduleItem,
)
from apps.leave.services.querysets import exclude_converted_paid_requests

from .base import LeaveTestCase


class LeaveDatabaseConstraintTests(LeaveTestCase):
    def _create_generation_run(self, schedule):
        return VacationScheduleGenerationRun.objects.create(
            schedule=schedule,
            year=schedule.year,
            mode=VacationScheduleGenerationRun.MODE_HYBRID,
            status=VacationScheduleGenerationRun.STATUS_COMPLETED,
            actor=self.hr_employee,
            candidates_count=2,
            selected_count=1,
            average_score=Decimal("87.50"),
        )

    def test_vacation_request_rejects_end_before_start(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            VacationRequest.objects.create(
                employee=self.employee,
                start_date=date(2026, 9, 10),
                end_date=date(2026, 9, 1),
                vacation_type="paid",
                status=VacationRequest.STATUS_PENDING,
            )

    def test_active_vacation_requests_cannot_overlap(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 10),
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            VacationRequest.objects.create(
                employee=self.employee,
                start_date=date(2026, 9, 5),
                end_date=date(2026, 9, 12),
                vacation_type="unpaid",
                status=VacationRequest.STATUS_PENDING,
            )

    def test_active_schedule_items_cannot_overlap(self):
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 10),
            vacation_type="paid",
            chargeable_days=10,
            status=VacationScheduleItem.STATUS_APPROVED,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            VacationScheduleItem.objects.create(
                schedule=schedule,
                employee=self.employee,
                start_date=date(2026, 7, 5),
                end_date=date(2026, 7, 14),
                vacation_type="paid",
                chargeable_days=10,
                status=VacationScheduleItem.STATUS_PLANNED,
            )

    def test_schedule_item_rejects_end_before_start(self):
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            VacationScheduleItem.objects.create(
                schedule=schedule,
                employee=self.employee,
                start_date=date(2026, 8, 10),
                end_date=date(2026, 8, 1),
                vacation_type="paid",
                chargeable_days=10,
                status=VacationScheduleItem.STATUS_APPROVED,
            )

    def test_active_request_cannot_overlap_active_schedule_item(self):
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 10),
            vacation_type="paid",
            chargeable_days=10,
            status=VacationScheduleItem.STATUS_APPROVED,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            VacationRequest.objects.create(
                employee=self.employee,
                start_date=date(2026, 7, 5),
                end_date=date(2026, 7, 7),
                vacation_type="unpaid",
                status=VacationRequest.STATUS_PENDING,
            )

    def test_linked_paid_request_schedule_item_is_allowed(self):
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        request_obj = VacationRequest.objects.create(
            employee=self.employee,
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 16),
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )

        schedule_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=request_obj.start_date,
            end_date=request_obj.end_date,
            vacation_type="paid",
            chargeable_days=7,
            status=VacationScheduleItem.STATUS_APPROVED,
            source=VacationScheduleItem.SOURCE_MANUAL,
            created_from_vacation_request=request_obj,
        )

        self.assertEqual(schedule_item.created_from_vacation_request_id, request_obj.id)

    def test_schedule_generation_candidate_links_to_selected_item(self):
        schedule = VacationSchedule.objects.create(
            year=2027,
            status=VacationSchedule.STATUS_DRAFT,
            created_by=self.hr_employee,
        )
        generation_run = self._create_generation_run(schedule)
        candidate = VacationScheduleCandidate.objects.create(
            generation_run=generation_run,
            schedule=schedule,
            employee=self.employee,
            start_date=date(2027, 8, 1),
            end_date=date(2027, 8, 14),
            chargeable_days=14,
            kind=VacationScheduleCandidate.KIND_PRIMARY_PREFERENCE,
            passed_hard_rules=True,
            risk_score=12,
            risk_level=VacationScheduleItem.RISK_LOW,
            features={"department_load_level": 1, "matches_preference": True},
            score=Decimal("87.50"),
            confidence=Decimal("76.00"),
            model_version="baseline-rules-v1",
            explanation="Период совпадает с пожеланием и не нарушает правила состава.",
            decision=VacationScheduleCandidate.DECISION_SELECTED,
            decision_rank=1,
            selected_at=timezone.now(),
        )

        item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=candidate.start_date,
            end_date=candidate.end_date,
            vacation_type="paid",
            chargeable_days=candidate.chargeable_days,
            status=VacationScheduleItem.STATUS_DRAFT,
            source=VacationScheduleItem.SOURCE_GENERATED,
            risk_score=candidate.risk_score,
            risk_level=candidate.risk_level,
            generated_by_ai=True,
            generation_run=generation_run,
            selected_candidate=candidate,
            ai_score=candidate.score,
            ai_confidence=candidate.confidence,
            ai_model_version=candidate.model_version,
            ai_explanation=candidate.explanation,
        )

        self.assertEqual(generation_run.candidates.count(), 1)
        self.assertEqual(generation_run.created_schedule_items.get(), item)
        self.assertEqual(candidate.selected_schedule_items.get(), item)
        self.assertEqual(item.ai_score, Decimal("87.50"))

    def test_only_active_linked_schedule_item_hides_converted_paid_request(self):
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        request_obj = VacationRequest.objects.create(
            employee=self.employee,
            start_date=date(2026, 12, 1),
            end_date=date(2026, 12, 7),
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        schedule_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=request_obj.start_date,
            end_date=request_obj.end_date,
            vacation_type="paid",
            chargeable_days=7,
            status=VacationScheduleItem.STATUS_APPROVED,
            source=VacationScheduleItem.SOURCE_MANUAL,
            created_from_vacation_request=request_obj,
        )

        request_queryset = VacationRequest.objects.filter(pk=request_obj.pk)
        self.assertFalse(exclude_converted_paid_requests(request_queryset).exists())

        schedule_item.status = VacationScheduleItem.STATUS_CANCELLED
        schedule_item.save(update_fields=["status"])

        self.assertTrue(exclude_converted_paid_requests(request_queryset).exists())

    def test_schedule_candidate_rejects_end_before_start(self):
        schedule = VacationSchedule.objects.create(
            year=2027,
            status=VacationSchedule.STATUS_DRAFT,
            created_by=self.hr_employee,
        )
        generation_run = self._create_generation_run(schedule)

        with self.assertRaises(IntegrityError), transaction.atomic():
            VacationScheduleCandidate.objects.create(
                generation_run=generation_run,
                schedule=schedule,
                employee=self.employee,
                start_date=date(2027, 9, 10),
                end_date=date(2027, 9, 1),
                chargeable_days=10,
            )

    def test_schedule_generation_scores_must_stay_in_percent_range(self):
        schedule = VacationSchedule.objects.create(
            year=2027,
            status=VacationSchedule.STATUS_DRAFT,
            created_by=self.hr_employee,
        )
        generation_run = self._create_generation_run(schedule)

        with self.assertRaises(IntegrityError), transaction.atomic():
            VacationScheduleCandidate.objects.create(
                generation_run=generation_run,
                schedule=schedule,
                employee=self.employee,
                start_date=date(2027, 10, 1),
                end_date=date(2027, 10, 14),
                chargeable_days=14,
                score=Decimal("101.00"),
            )

        with self.assertRaises(IntegrityError), transaction.atomic():
            VacationScheduleItem.objects.create(
                schedule=schedule,
                employee=self.employee,
                start_date=date(2027, 11, 1),
                end_date=date(2027, 11, 14),
                vacation_type="paid",
                chargeable_days=14,
                status=VacationScheduleItem.STATUS_DRAFT,
                ai_score=Decimal("101.00"),
            )
