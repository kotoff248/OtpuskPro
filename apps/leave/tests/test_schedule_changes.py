from datetime import date

from django.core.exceptions import ValidationError

from apps.leave.models import VacationSchedule, VacationScheduleChangeRequest, VacationScheduleItem
from apps.leave.services.schedule_changes import (
    approve_schedule_change_request,
    create_schedule_change_request,
    reject_schedule_change_request,
)

from .base import LeaveTestCase


class ScheduleChangeRequestTests(LeaveTestCase):
    def test_schedule_change_request_approves_by_replacing_old_item(self):
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        schedule_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
        )

        change_request = create_schedule_change_request(
            schedule_item.id,
            requested_by=self.employee,
            new_start_date=date(2026, 8, 1),
            new_end_date=date(2026, 8, 14),
            reason="Нужно перенести по семейным обстоятельствам.",
        )
        schedule_item.refresh_from_db()

        self.assertEqual(change_request.status, VacationScheduleChangeRequest.STATUS_PENDING)
        self.assertEqual(schedule_item.status, VacationScheduleItem.STATUS_APPROVED)

        replacement = approve_schedule_change_request(change_request.id, reviewer=self.department_head)
        schedule_item.refresh_from_db()
        change_request.refresh_from_db()

        self.assertEqual(schedule_item.status, VacationScheduleItem.STATUS_TRANSFERRED)
        self.assertEqual(change_request.status, VacationScheduleChangeRequest.STATUS_APPROVED)
        self.assertEqual(replacement.previous_item_id, schedule_item.id)
        self.assertEqual(replacement.created_from_change_request_id, change_request.id)
        self.assertEqual(replacement.source, VacationScheduleItem.SOURCE_TRANSFER)
        self.assertEqual(replacement.chargeable_days, 14)

    def test_rejected_schedule_change_does_not_modify_schedule_item(self):
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        schedule_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        change_request = create_schedule_change_request(
            schedule_item.id,
            requested_by=self.employee,
            new_start_date=date(2026, 8, 1),
            new_end_date=date(2026, 8, 14),
            reason="Нужно перенести.",
        )

        reject_schedule_change_request(change_request.id, reviewer=self.department_head)
        schedule_item.refresh_from_db()
        change_request.refresh_from_db()

        self.assertEqual(schedule_item.status, VacationScheduleItem.STATUS_APPROVED)
        self.assertEqual(change_request.status, VacationScheduleChangeRequest.STATUS_REJECTED)
        self.assertFalse(VacationScheduleItem.objects.filter(previous_item=schedule_item).exists())

    def test_schedule_change_approve_requires_valid_reviewer(self):
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        schedule_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        change_request = create_schedule_change_request(
            schedule_item.id,
            requested_by=self.employee,
            new_start_date=date(2026, 8, 1),
            new_end_date=date(2026, 8, 14),
        )

        for reviewer in (None, self.employee, self.foreign_department_head, self.hr_employee):
            with self.subTest(reviewer=reviewer):
                with self.assertRaises(ValidationError):
                    approve_schedule_change_request(change_request.id, reviewer=reviewer)

        change_request.refresh_from_db()
        schedule_item.refresh_from_db()
        self.assertEqual(change_request.status, VacationScheduleChangeRequest.STATUS_PENDING)
        self.assertEqual(schedule_item.status, VacationScheduleItem.STATUS_APPROVED)

    def test_schedule_change_reject_requires_valid_reviewer(self):
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        schedule_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        change_request = create_schedule_change_request(
            schedule_item.id,
            requested_by=self.employee,
            new_start_date=date(2026, 10, 1),
            new_end_date=date(2026, 10, 14),
        )

        with self.assertRaises(ValidationError):
            reject_schedule_change_request(change_request.id, reviewer=self.employee)
        with self.assertRaises(ValidationError):
            reject_schedule_change_request(change_request.id, reviewer=None)

        change_request.refresh_from_db()
        self.assertEqual(change_request.status, VacationScheduleChangeRequest.STATUS_PENDING)
