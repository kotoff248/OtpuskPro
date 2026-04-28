from datetime import date

from django.db import IntegrityError, transaction

from apps.leave.models import VacationRequest, VacationSchedule, VacationScheduleItem

from .base import LeaveTestCase


class LeaveDatabaseConstraintTests(LeaveTestCase):
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
