from datetime import date

from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounts.services import sync_employee_user
from apps.employees.models import Employees
from apps.leave.models import (
    VacationEntitlementAllocation,
    VacationRequest,
    VacationSchedule,
    VacationScheduleItem,
)
from apps.leave.services.dates import get_chargeable_leave_days
from apps.leave.services.ledger import get_employee_leave_summary
from apps.leave.services.metrics import set_vacation_metric_sync_enabled
from apps.leave.services.requests import approve_vacation_request, create_vacation_request
from apps.leave.services.validation import get_paid_request_eligibility_for_year

from .base import LeaveTestCase


class VacationRequestTests(LeaveTestCase):
    def test_rejected_request_does_not_block_new_request(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-08-11",
            end_date="2026-08-15",
            vacation_type="unpaid",
            status=VacationRequest.STATUS_REJECTED,
        )

        self.client.force_login(self.employee.user)
        response = self.client.post(
            reverse("calendar"),
            {
                "type_vacation": "unpaid",
                "start_date": "2026-08-11",
                "end_date": "2026-08-15",
                "next_view_mode": "month",
                "next_year": "2026",
                "next_month": "8",
            },
        )

        self.assertRedirects(response, f'{reverse("calendar")}?view=month&year=2026&month=8')
        self.assertTrue(
            VacationRequest.objects.filter(
                employee=self.employee,
                start_date="2026-08-11",
                end_date="2026-08-15",
                status=VacationRequest.STATUS_PENDING,
            ).exists()
        )

    def test_paid_request_uses_free_balance_even_when_employee_has_schedule(self):
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        allowed, _ = get_paid_request_eligibility_for_year(self.employee, 2026, as_of_date=date(2026, 9, 1))

        self.client.force_login(self.employee.user)
        response = self.client.post(
            reverse("calendar"),
            {
                "type_vacation": "paid",
                "start_date": "2026-09-01",
                "end_date": "2026-09-07",
                "next_view_mode": "month",
                "next_year": "2026",
                "next_month": "9",
            },
        )

        self.assertTrue(allowed)
        self.assertRedirects(response, f'{reverse("calendar")}?view=month&year=2026&month=9')
        self.assertTrue(
            VacationRequest.objects.filter(
                employee=self.employee,
                vacation_type="paid",
                start_date="2026-09-01",
                status=VacationRequest.STATUS_PENDING,
            ).exists()
        )

    def test_paid_request_is_blocked_when_balance_is_fully_reserved(self):
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        limited_employee = Employees.objects.create(
            last_name="Лимитов",
            first_name="Петр",
            middle_name="Сергеевич",
            login="reserved-balance-employee",
            position="Специалист",
            department=self.engineering,
            date_joined=date(2026, 1, 1),
            annual_paid_leave_days=5,
            role=Employees.ROLE_EMPLOYEE,
        )
        sync_employee_user(limited_employee, raw_password="reserved-pass")
        VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=limited_employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 5),
            vacation_type="paid",
            chargeable_days=5,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        allowed, _ = get_paid_request_eligibility_for_year(limited_employee, 2026, as_of_date=date(2026, 9, 1))

        self.assertFalse(allowed)
        with self.assertRaises(ValidationError):
            create_vacation_request(
                employee=limited_employee,
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 2),
                vacation_type="paid",
            )

    def test_new_hire_without_schedule_can_create_paid_exception_after_six_months(self):
        VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        newcomer = Employees.objects.create(
            last_name="Новиков",
            first_name="Артем",
            middle_name="Сергеевич",
            login="new-hire-paid-exception",
            position="Инженер",
            department=self.engineering,
            date_joined=date(2026, 1, 10),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        allowed, _ = get_paid_request_eligibility_for_year(newcomer, 2026, as_of_date=date(2026, 9, 1))

        with self.assertRaises(ValidationError):
            create_vacation_request(
                employee=newcomer,
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 7),
                vacation_type="paid",
            )
        request_obj = create_vacation_request(
            employee=newcomer,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 7),
            vacation_type="paid",
            reason="Отпуск после шести месяцев работы.",
        )

        self.assertTrue(allowed)
        self.assertEqual(request_obj.status, VacationRequest.STATUS_PENDING)
        self.assertEqual(request_obj.vacation_type, "paid")

    def test_approved_paid_request_creates_manual_schedule_item_without_double_balance(self):
        VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        pending_request = VacationRequest.objects.create(
            employee=self.employee,
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 16),
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )

        approved_request = approve_vacation_request(pending_request.id, reviewer=self.department_head)
        approved_request.refresh_from_db()
        schedule_item = approved_request.created_schedule_items.get()
        chargeable_days = get_chargeable_leave_days(
            approved_request.start_date,
            approved_request.end_date,
            approved_request.vacation_type,
        )
        summary = get_employee_leave_summary(self.employee, as_of_date=date(2026, 12, 31))

        self.assertEqual(approved_request.status, VacationRequest.STATUS_APPROVED)
        self.assertEqual(schedule_item.source, VacationScheduleItem.SOURCE_MANUAL)
        self.assertEqual(schedule_item.status, VacationScheduleItem.STATUS_APPROVED)
        self.assertFalse(schedule_item.generated_by_ai)
        self.assertEqual(schedule_item.chargeable_days, chargeable_days)
        self.assertFalse(VacationEntitlementAllocation.objects.filter(vacation_request=approved_request).exists())
        self.assertTrue(VacationEntitlementAllocation.objects.filter(schedule_item=schedule_item).exists())
        self.assertEqual(summary["used"], chargeable_days)

    def test_unpaid_and_study_approvals_do_not_create_schedule_items(self):
        unpaid_request = VacationRequest.objects.create(
            employee=self.employee,
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 3),
            vacation_type="unpaid",
            status=VacationRequest.STATUS_PENDING,
        )
        study_request = VacationRequest.objects.create(
            employee=self.employee,
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 5),
            vacation_type="study",
            status=VacationRequest.STATUS_PENDING,
        )

        approve_vacation_request(unpaid_request.id, reviewer=self.department_head)
        approve_vacation_request(study_request.id, reviewer=self.department_head)

        unpaid_request.refresh_from_db()
        study_request.refresh_from_db()
        self.assertEqual(unpaid_request.status, VacationRequest.STATUS_APPROVED)
        self.assertEqual(study_request.status, VacationRequest.STATUS_APPROVED)
        self.assertFalse(unpaid_request.created_schedule_items.exists())
        self.assertFalse(study_request.created_schedule_items.exists())

    def test_approve_fails_when_balance_insufficient(self):
        limited_employee = Employees.objects.create(
            last_name="Лимитов",
            first_name="Петр",
            middle_name="Сергеевич",
            login="limited-balance",
            position="Специалист",
            department=self.engineering,
            date_joined=date(2026, 1, 1),
            annual_paid_leave_days=5,
            role=Employees.ROLE_EMPLOYEE,
        )
        VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        previous_sync_state = set_vacation_metric_sync_enabled(False)
        try:
            pending_request = VacationRequest.objects.create(
                employee=limited_employee,
                start_date="2026-09-01",
                end_date="2026-09-10",
                vacation_type="paid",
                status=VacationRequest.STATUS_PENDING,
            )
        finally:
            set_vacation_metric_sync_enabled(previous_sync_state)

        with self.assertRaises(ValidationError):
            approve_vacation_request(pending_request.id)

    def test_approve_fails_when_dates_conflict(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-09-10",
            end_date="2026-09-12",
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        pending_request = VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-09-11",
            end_date="2026-09-13",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )

        with self.assertRaises(ValidationError):
            approve_vacation_request(pending_request.id)
