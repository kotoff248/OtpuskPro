from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.services import sync_employee_user
from apps.employees.models import Departments, Employees
from apps.leave.models import VacationRequest
from apps.leave.services import (
    approve_vacation_request,
    build_analytics_payload,
    build_calendar_base_data,
    build_calendar_rows,
    get_chargeable_leave_days,
    get_employee_accrued_leave,
    get_employee_list_leave_summaries,
    get_employee_leave_summaries,
    get_employee_leave_summary,
    get_employee_requestable_leave,
    sync_employee_vacation_metrics,
)


class VacationRulesTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.engineering = Departments.objects.create(name="Engineering")
        self.hr_department = Departments.objects.create(name="HR")

        self.employee = Employees.objects.create(
            last_name="Календарев",
            first_name="Иван",
            middle_name="Петрович",
            login="calendar-user",
            position="Специалист",
            department=self.engineering,
            date_joined=self.today - timedelta(days=420),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        sync_employee_user(self.employee, raw_password="employee-pass")

        self.department_head = Employees.objects.create(
            last_name="Планова",
            first_name="Мария",
            middle_name="Игоревна",
            login="calendar-dept-head",
            position="Руководитель отдела",
            department=self.engineering,
            date_joined=self.today - timedelta(days=800),
            annual_paid_leave_days=52,
            role=Employees.ROLE_DEPARTMENT_HEAD,
        )
        sync_employee_user(self.department_head, raw_password="dept-head-pass")

        self.enterprise_head = Employees.objects.create(
            last_name="Директоров",
            first_name="Олег",
            middle_name="Игоревич",
            login="calendar-enterprise-head",
            position="Директор",
            department=self.hr_department,
            date_joined=self.today - timedelta(days=900),
            annual_paid_leave_days=52,
            role=Employees.ROLE_ENTERPRISE_HEAD,
        )
        sync_employee_user(self.enterprise_head, raw_password="enterprise-pass")

        self.hr_employee = Employees.objects.create(
            last_name="Кадрова",
            first_name="Анна",
            middle_name="Сергеевна",
            login="calendar-hr",
            position="HR",
            department=self.hr_department,
            date_joined=self.today - timedelta(days=700),
            annual_paid_leave_days=52,
            role=Employees.ROLE_HR,
        )
        sync_employee_user(self.hr_employee, raw_password="hr-pass")

        self.authorized_person = Employees.objects.create(
            last_name="Админова",
            first_name="Инна",
            middle_name="Олеговна",
            login="authorized-person",
            position="Уполномоченное лицо",
            date_joined=self.today - timedelta(days=1000),
            annual_paid_leave_days=52,
            role=Employees.ROLE_AUTHORIZED_PERSON,
        )
        sync_employee_user(self.authorized_person, raw_password="authorized-pass")

        self.outsider = Employees.objects.create(
            last_name="Чужой",
            first_name="Петр",
            middle_name="Сергеевич",
            login="other-department-user",
            position="Аналитик",
            department=self.hr_department,
            date_joined=self.today - timedelta(days=300),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        sync_employee_user(self.outsider, raw_password="outsider-pass")

        self.foreign_department_head = Employees.objects.create(
            last_name="Другой",
            first_name="Роман",
            middle_name="Олегович",
            login="foreign-department-head",
            position="Руководитель отдела",
            department=self.hr_department,
            date_joined=self.today - timedelta(days=850),
            annual_paid_leave_days=52,
            role=Employees.ROLE_DEPARTMENT_HEAD,
        )
        sync_employee_user(self.foreign_department_head, raw_password="foreign-head-pass")

    def test_rejected_request_does_not_block_new_request(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-08-11",
            end_date="2026-08-15",
            vacation_type="paid",
            status=VacationRequest.STATUS_REJECTED,
        )

        self.client.force_login(self.employee.user)
        response = self.client.post(
            reverse("calendar"),
            {
                "type_vacation": "paid",
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

    def test_approve_fails_when_balance_insufficient(self):
        limited_employee = Employees.objects.create(
            last_name="Лимитов",
            first_name="Петр",
            middle_name="Сергеевич",
            login="limited-balance",
            position="Специалист",
            department=self.engineering,
            date_joined=self.today - timedelta(days=220),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        VacationRequest.objects.create(
            employee=limited_employee,
            start_date="2026-07-01",
            end_date="2026-08-19",
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        sync_employee_vacation_metrics(limited_employee)

        pending_request = VacationRequest.objects.create(
            employee=limited_employee,
            start_date="2026-09-01",
            end_date="2026-09-03",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )

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

    def test_unpaid_vacation_does_not_reduce_balance(self):
        request_obj = VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-10-01",
            end_date="2026-10-05",
            vacation_type="unpaid",
            status=VacationRequest.STATUS_APPROVED,
        )
        sync_employee_vacation_metrics(self.employee)
        self.employee.refresh_from_db()

        self.assertEqual(request_obj.vacation_type, "unpaid")
        self.assertEqual(self.employee.used_up_days, 0)

    def test_holiday_days_do_not_reduce_paid_balance(self):
        self.assertEqual(get_chargeable_leave_days(date(2026, 1, 1), date(2026, 1, 8), "paid"), 0)

        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-01-01",
            end_date="2026-01-08",
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        sync_employee_vacation_metrics(self.employee)
        self.employee.refresh_from_db()

        self.assertEqual(self.employee.used_up_days, 0)

    def test_less_than_six_months_requestable_balance_matches_accrued(self):
        newcomer = Employees.objects.create(
            last_name="Новичков",
            first_name="Олег",
            middle_name="Сергеевич",
            login="newcomer",
            position="Стажер",
            department=self.engineering,
            date_joined=self.today - timedelta(days=45),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )

        accrued = get_employee_accrued_leave(newcomer, self.today)
        requestable = get_employee_requestable_leave(newcomer, self.today)

        self.assertEqual(accrued, requestable)
        self.assertLess(requestable, 52)

    def test_after_six_months_employee_can_use_advance(self):
        six_month_employee = Employees.objects.create(
            last_name="Северов",
            first_name="Павел",
            middle_name="Андреевич",
            login="north-employee",
            position="Инженер",
            department=self.engineering,
            date_joined=self.today - timedelta(days=190),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )

        accrued = get_employee_accrued_leave(six_month_employee, self.today)
        requestable = get_employee_requestable_leave(six_month_employee, self.today)

        self.assertLess(accrued, 52)
        self.assertEqual(requestable, 52)

    def test_second_working_year_does_not_require_waiting_another_six_months(self):
        experienced_employee = Employees.objects.create(
            last_name="Опытный",
            first_name="Алексей",
            middle_name="Игоревич",
            login="experienced-employee",
            position="Инженер",
            department=self.engineering,
            date_joined=self.today - timedelta(days=420),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )

        accrued = get_employee_accrued_leave(experienced_employee, self.today)
        requestable = get_employee_requestable_leave(experienced_employee, self.today)

        self.assertLess(accrued, 104)
        self.assertEqual(requestable, 104)

    def test_available_balance_uses_requestable_for_subsequent_working_years(self):
        experienced_employee = Employees.objects.create(
            last_name="Балансов",
            first_name="Павел",
            middle_name="Сергеевич",
            login="experienced-balance",
            position="Ведущий инженер",
            department=self.engineering,
            date_joined=self.today - timedelta(days=420),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        VacationRequest.objects.create(
            employee=experienced_employee,
            start_date=self.today - timedelta(days=300),
            end_date=self.today - timedelta(days=287),
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )

        summary = get_employee_leave_summary(experienced_employee, self.today)

        self.assertEqual(summary["requestable"], 104)
        self.assertEqual(summary["used"], 14)
        self.assertEqual(summary["available"], 90)
        self.assertEqual(summary["accrued_balance"], summary["accrued"] - 14)
        self.assertEqual(summary["advance_available"], summary["available"] - summary["accrued_balance"])

    def test_leave_summary_exposes_advance_breakdown(self):
        six_month_employee = Employees.objects.create(
            last_name="Авансов",
            first_name="Иван",
            middle_name="Петрович",
            login="advance-breakdown",
            position="Инженер",
            department=self.engineering,
            date_joined=self.today - timedelta(days=190),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        VacationRequest.objects.create(
            employee=six_month_employee,
            start_date=self.today - timedelta(days=20),
            end_date=self.today - timedelta(days=6),
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )

        summary = get_employee_leave_summary(six_month_employee, self.today)
        positive_accrued_balance = max(summary["accrued_balance"], 0)

        self.assertLess(summary["accrued"], summary["requestable"])
        self.assertEqual(summary["accrued_balance"], summary["accrued"] - summary["used"] - summary["reserved"])
        self.assertEqual(summary["advance_available"], summary["available"] - positive_accrued_balance)

    def test_bulk_leave_summary_matches_single_employee_calculation(self):
        teammate = Employees.objects.create(
            last_name="Командный",
            first_name="Игорь",
            middle_name="Сергеевич",
            login="teammate-bulk",
            position="Инженер",
            department=self.engineering,
            date_joined=self.today - timedelta(days=650),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )

        VacationRequest.objects.create(
            employee=self.employee,
            start_date=self.today - timedelta(days=60),
            end_date=self.today - timedelta(days=46),
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        VacationRequest.objects.create(
            employee=self.employee,
            start_date=self.today + timedelta(days=30),
            end_date=self.today + timedelta(days=36),
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        VacationRequest.objects.create(
            employee=teammate,
            start_date=self.today - timedelta(days=45),
            end_date=self.today - timedelta(days=36),
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )

        bulk_summaries = get_employee_leave_summaries([self.employee, teammate], as_of_date=self.today)

        self.assertEqual(bulk_summaries[self.employee.id], get_employee_leave_summary(self.employee, self.today))
        self.assertEqual(bulk_summaries[teammate.id], get_employee_leave_summary(teammate, self.today))

    def test_employee_list_leave_summary_matches_full_summary_for_display_fields(self):
        teammate = Employees.objects.create(
            last_name="РЎРїРёСЃРєРѕРІ",
            first_name="РђРЅРґСЂРµР№",
            middle_name="РРіРѕСЂРµРІРёС‡",
            login="list-summary-employee",
            position="РРЅР¶РµРЅРµСЂ",
            department=self.engineering,
            date_joined=self.today - timedelta(days=510),
            annual_paid_leave_days=52,
            manual_leave_adjustment_days=3,
            role=Employees.ROLE_EMPLOYEE,
        )

        VacationRequest.objects.create(
            employee=self.employee,
            start_date=self.today - timedelta(days=30),
            end_date=self.today - timedelta(days=21),
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        VacationRequest.objects.create(
            employee=self.employee,
            start_date=self.today + timedelta(days=15),
            end_date=self.today + timedelta(days=19),
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        VacationRequest.objects.create(
            employee=teammate,
            start_date=self.today - timedelta(days=80),
            end_date=self.today - timedelta(days=68),
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        VacationRequest.objects.create(
            employee=teammate,
            start_date=self.today + timedelta(days=40),
            end_date=self.today + timedelta(days=46),
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )

        self.employee.refresh_from_db()
        teammate.refresh_from_db()
        list_summaries = get_employee_list_leave_summaries([self.employee, teammate], as_of_date=self.today)

        for employee in (self.employee, teammate):
            full_summary = get_employee_leave_summary(employee, self.today)
            list_summary = list_summaries[employee.id]
            self.assertEqual(list_summary["requestable"], full_summary["requestable"])
            self.assertEqual(list_summary["used"], full_summary["used"])
            self.assertEqual(list_summary["reserved"], full_summary["reserved"])
            self.assertEqual(list_summary["available"], full_summary["available"])

    def test_applications_ajax_returns_only_department_scope_for_department_head(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-11-01",
            end_date="2026-11-03",
            vacation_type="study",
            status=VacationRequest.STATUS_PENDING,
        )
        VacationRequest.objects.create(
            employee=self.outsider,
            start_date="2026-11-05",
            end_date="2026-11-07",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        self.client.force_login(self.department_head.user)

        response = self.client.get(
            reverse("applications"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["vacations"]), 1)
        self.assertEqual(payload["vacations"][0]["employee_name"], self.employee.full_name)

    def test_calendar_ajax_returns_partial_results_for_view_switch(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-07-10",
            end_date="2026-07-14",
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        self.client.force_login(self.employee.user)

        response = self.client.get(
            reverse("calendar"),
            {"view": "year", "year": 2026},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("html", payload)
        self.assertIn("calendar_details", payload)
        self.assertIn("year-board", payload["html"])
        self.assertIn(str(self.employee.id), payload["calendar_details"])

    def test_employee_cannot_open_management_sections(self):
        self.client.force_login(self.employee.user)

        applications_response = self.client.get(reverse("applications"))
        analytics_response = self.client.get(reverse("analytics"))

        self.assertRedirects(applications_response, reverse("main"))
        self.assertRedirects(analytics_response, reverse("main"))

    def test_hr_can_view_all_applications_but_cannot_approve(self):
        request_obj = VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-12-01",
            end_date="2026-12-02",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        self.client.force_login(self.hr_employee.user)

        applications_response = self.client.get(reverse("applications"))
        approve_response = self.client.post(reverse("approve_vacation", args=[request_obj.id]))
        request_obj.refresh_from_db()

        self.assertEqual(applications_response.status_code, 200)
        self.assertContains(applications_response, self.employee.full_name)
        self.assertRedirects(approve_response, reverse("vacation_detail", args=[request_obj.id]))
        self.assertEqual(request_obj.status, VacationRequest.STATUS_PENDING)

    def test_enterprise_head_can_approve_department_head_but_not_regular_employee(self):
        department_head_request = VacationRequest.objects.create(
            employee=self.department_head,
            start_date="2026-12-01",
            end_date="2026-12-02",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        request_obj = VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-12-05",
            end_date="2026-12-06",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        self.client.force_login(self.enterprise_head.user)

        applications_response = self.client.get(reverse("applications"))
        approve_department_head_response = self.client.post(reverse("approve_vacation", args=[department_head_request.id]))
        approve_regular_employee_response = self.client.post(reverse("approve_vacation", args=[request_obj.id]))

        department_head_request.refresh_from_db()
        request_obj.refresh_from_db()

        self.assertEqual(applications_response.status_code, 200)
        self.assertContains(applications_response, self.department_head.full_name)
        self.assertNotContains(applications_response, self.employee.full_name)
        self.assertRedirects(approve_department_head_response, reverse("applications"))
        self.assertEqual(department_head_request.status, VacationRequest.STATUS_APPROVED)
        self.assertRedirects(approve_regular_employee_response, reverse("vacation_detail", args=[request_obj.id]))
        self.assertEqual(request_obj.status, VacationRequest.STATUS_PENDING)

    def test_department_head_can_approve_only_own_department_requests(self):
        own_request = VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-12-10",
            end_date="2026-12-12",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        foreign_request = VacationRequest.objects.create(
            employee=self.outsider,
            start_date="2026-12-15",
            end_date="2026-12-17",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        foreign_head_request = VacationRequest.objects.create(
            employee=self.foreign_department_head,
            start_date="2026-12-20",
            end_date="2026-12-21",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        self.client.force_login(self.department_head.user)

        approve_own_response = self.client.post(reverse("approve_vacation", args=[own_request.id]))
        approve_foreign_response = self.client.post(reverse("approve_vacation", args=[foreign_request.id]))
        approve_foreign_head_response = self.client.post(reverse("approve_vacation", args=[foreign_head_request.id]))

        own_request.refresh_from_db()
        foreign_request.refresh_from_db()
        foreign_head_request.refresh_from_db()

        self.assertRedirects(approve_own_response, reverse("applications"))
        self.assertEqual(own_request.status, VacationRequest.STATUS_APPROVED)
        self.assertEqual(approve_foreign_response.status_code, 302)
        self.assertEqual(approve_foreign_response.url, reverse("vacation_detail", args=[foreign_request.id]))
        self.assertEqual(approve_foreign_head_response.status_code, 302)
        self.assertEqual(approve_foreign_head_response.url, reverse("vacation_detail", args=[foreign_head_request.id]))
        self.assertEqual(foreign_request.status, VacationRequest.STATUS_PENDING)
        self.assertEqual(foreign_head_request.status, VacationRequest.STATUS_PENDING)

    def test_authorized_person_can_approve_only_enterprise_head_requests(self):
        enterprise_request = VacationRequest.objects.create(
            employee=self.enterprise_head,
            start_date="2026-12-10",
            end_date="2026-12-12",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        department_head_request = VacationRequest.objects.create(
            employee=self.department_head,
            start_date="2026-12-15",
            end_date="2026-12-17",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        self.client.force_login(self.authorized_person.user)

        applications_response = self.client.get(reverse("applications"))
        approve_enterprise_response = self.client.post(reverse("approve_vacation", args=[enterprise_request.id]))
        approve_department_head_response = self.client.post(reverse("approve_vacation", args=[department_head_request.id]))

        enterprise_request.refresh_from_db()
        department_head_request.refresh_from_db()

        self.assertEqual(applications_response.status_code, 200)
        self.assertContains(applications_response, self.enterprise_head.full_name)
        self.assertNotContains(applications_response, self.department_head.full_name)
        self.assertRedirects(approve_enterprise_response, reverse("applications"))
        self.assertEqual(enterprise_request.status, VacationRequest.STATUS_APPROVED)
        self.assertEqual(approve_department_head_response.status_code, 302)
        self.assertEqual(
            approve_department_head_response.url,
            reverse("vacation_detail", args=[department_head_request.id]),
        )
        self.assertEqual(department_head_request.status, VacationRequest.STATUS_PENDING)

    def test_enterprise_head_cannot_approve_own_request(self):
        own_request = VacationRequest.objects.create(
            employee=self.enterprise_head,
            start_date="2026-12-22",
            end_date="2026-12-23",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        self.client.force_login(self.enterprise_head.user)

        response = self.client.post(reverse("approve_vacation", args=[own_request.id]))
        own_request.refresh_from_db()

        self.assertRedirects(response, reverse("vacation_detail", args=[own_request.id]))
        self.assertEqual(own_request.status, VacationRequest.STATUS_PENDING)

    def test_department_head_analytics_are_limited_to_own_department(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date=date(2026, 1, 30),
            end_date=date(2026, 2, 2),
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        VacationRequest.objects.create(
            employee=self.outsider,
            start_date=date(2026, 1, 10),
            end_date=date(2026, 1, 12),
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        self.client.force_login(self.department_head.user)

        response = self.client.get(reverse("analytics"))

        self.assertEqual(response.status_code, 200)
        row_employee_ids = {row["employee_id"] for row in response.context["rows"]}
        self.assertIn(self.employee.id, row_employee_ids)
        self.assertNotIn(self.outsider.id, row_employee_ids)

    def test_analytics_split_duration_by_month_overlap(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date=date(2026, 1, 30),
            end_date=date(2026, 2, 2),
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )

        payload = build_analytics_payload()

        self.assertEqual(payload["values1"][0], 1)
        self.assertEqual(payload["values1"][1], 1)
        self.assertEqual(payload["values2"][0], 2)
        self.assertEqual(payload["values2"][1], 2)
        self.assertEqual(payload["values3"][0], 2)
        self.assertEqual(payload["values3"][1], 2)

    def test_vacation_detail_renders_role_based_action_forms(self):
        request_obj = VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-12-15",
            end_date="2026-12-17",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )

        self.client.force_login(self.department_head.user)
        manager_response = self.client.get(reverse("vacation_detail", args=[request_obj.id]))

        self.client.force_login(self.enterprise_head.user)
        enterprise_response = self.client.get(reverse("vacation_detail", args=[request_obj.id]))

        self.assertEqual(manager_response.status_code, 200)
        self.assertContains(manager_response, reverse("approve_vacation", args=[request_obj.id]))
        self.assertContains(manager_response, reverse("reject_vacation", args=[request_obj.id]))
        self.assertContains(manager_response, reverse("delete_vacation", args=[request_obj.id]))
        self.assertContains(manager_response, "Можно запланировать сейчас")
        self.assertContains(manager_response, "Начислено по стажу")

        self.assertEqual(enterprise_response.status_code, 200)
        self.assertNotContains(enterprise_response, reverse("approve_vacation", args=[request_obj.id]))
        self.assertNotContains(enterprise_response, reverse("reject_vacation", args=[request_obj.id]))

    def test_authorized_person_sees_action_forms_for_enterprise_head_request(self):
        request_obj = VacationRequest.objects.create(
            employee=self.enterprise_head,
            start_date="2026-12-20",
            end_date="2026-12-22",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        self.client.force_login(self.authorized_person.user)

        response = self.client.get(reverse("vacation_detail", args=[request_obj.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("approve_vacation", args=[request_obj.id]))
        self.assertContains(response, reverse("reject_vacation", args=[request_obj.id]))

    def test_authorized_person_has_only_applications_access(self):
        self.client.force_login(self.authorized_person.user)

        main_response = self.client.get(reverse("main"))
        applications_response = self.client.get(reverse("applications"))
        employees_response = self.client.get(reverse("employees"))
        calendar_response = self.client.get(reverse("calendar"))
        profile_response = self.client.get(reverse("employee_profile", args=[self.authorized_person.id]))

        self.assertRedirects(main_response, reverse("applications"))
        self.assertEqual(applications_response.status_code, 200)
        self.assertNotContains(applications_response, "Профиль")
        self.assertContains(applications_response, "Служебный доступ")
        self.assertRedirects(employees_response, reverse("applications"))
        self.assertRedirects(calendar_response, reverse("applications"))
        self.assertRedirects(profile_response, reverse("applications"))

    def test_calendar_page_uses_shared_vacation_modal_hooks(self):
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("calendar"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-modal-open="vacation-modal"')
        self.assertContains(response, 'id="vacation-modal"')
        self.assertContains(response, 'id="chargeable_days"')
        self.assertContains(response, 'id="calendar-charge-preview"')
        self.assertContains(response, 'data-modal-close')
        self.assertContains(response, 'data-date-field')

    def test_calendar_page_renders_only_visible_employee_rows_for_regular_employee(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-11-01",
            end_date="2026-11-03",
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        VacationRequest.objects.create(
            employee=self.outsider,
            start_date="2026-11-05",
            end_date="2026-11-07",
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("calendar"), {"view": "year", "year": 2026})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.employee.full_name)
        self.assertNotContains(response, self.outsider.full_name)

    def test_calendar_rows_include_rejected_requests_in_month_and_year_views(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-05-10",
            end_date="2026-05-12",
            vacation_type="paid",
            status=VacationRequest.STATUS_REJECTED,
        )

        employees, employee_day_status, employee_entries = build_calendar_base_data(2026)
        month_rows, month_details = build_calendar_rows(
            employees,
            employee_day_status,
            employee_entries,
            year=2026,
            month=5,
            view_mode="month",
            today=date(2026, 5, 1),
        )
        year_rows, _ = build_calendar_rows(
            employees,
            employee_day_status,
            employee_entries,
            year=2026,
            month=5,
            view_mode="year",
            today=date(2026, 5, 1),
        )

        month_row = next(row for row in month_rows if row["employee_id"] == self.employee.id)
        year_row = next(row for row in year_rows if row["employee_id"] == self.employee.id)
        may_cell = year_row["cells"][4]

        self.assertEqual(month_row["selected_rejected_days"], 3)
        self.assertEqual(month_row["status"], VacationRequest.STATUS_REJECTED)
        self.assertEqual(year_row["year_rejected_days"], 3)
        self.assertEqual(may_cell["rejected_days"], 3)
        self.assertEqual(may_cell["status"], VacationRequest.STATUS_REJECTED)
        self.assertEqual(month_details[str(self.employee.id)]["selected_rejected_days"], 3)

    def test_year_view_segments_follow_real_dates_across_month_boundary(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-03-19",
            end_date="2026-04-01",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )

        employees, employee_day_status, employee_entries = build_calendar_base_data(2026)
        rows, _ = build_calendar_rows(
            employees,
            employee_day_status,
            employee_entries,
            year=2026,
            month=3,
            view_mode="year",
            today=date(2026, 3, 1),
        )

        row = next(row for row in rows if row["employee_id"] == self.employee.id)
        march_cell = row["cells"][2]
        april_cell = row["cells"][3]

        self.assertEqual(march_cell["pending_days"], 13)
        self.assertEqual(len(march_cell["segments"]), 1)
        self.assertEqual(march_cell["segments"][0]["offset_percent"], 58.1)
        self.assertEqual(march_cell["segments"][0]["width_percent"], 41.9)
        self.assertEqual(april_cell["pending_days"], 1)
        self.assertEqual(len(april_cell["segments"]), 1)
        self.assertEqual(april_cell["segments"][0]["offset_percent"], 0.0)
        self.assertEqual(april_cell["segments"][0]["width_percent"], 3.3)
