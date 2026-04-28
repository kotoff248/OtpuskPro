from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.services import sync_employee_user
from apps.employees.models import Employees
from apps.leave.models import VacationSchedule, VacationScheduleItem

from .base import EmployeeTestCase


class EmployeeRegistryTests(EmployeeTestCase):
    def test_employees_page_uses_shared_create_modal_shell_for_hr(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("employees"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="employee-create-modal"')
        self.assertContains(response, 'data-modal-open="employee-create-modal"')
        self.assertContains(response, 'class="department-summary-card department-summary-card--employees"')
        self.assertContains(response, 'id="employees-count"')
        self.assertContains(response, 'id="department"')
        self.assertContains(response, 'data-employee-submit disabled')
        self.assertContains(response, "js/employee-form.js")
        self.assertContains(response, "js/employees-page.js")
        self.assertContains(response, 'class="employee-card employee-row employee-row-clickable is-clickable"')
        self.assertNotContains(response, "<table", html=False)

    def test_department_head_sees_only_managed_department_on_employees_page(self):
        self.client.force_login(self.department_head.user)

        response = self.client.get(reverse("employees"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.employee.full_name)
        self.assertNotContains(response, self.outsider.full_name)
        self.assertNotContains(response, 'employee-create-modal')
        self.assertNotContains(response, 'id="department"')
        self.assertContains(response, 'class="department-summary-card department-summary-card--employees"')

    def test_employees_page_ajax_response_contains_card_fields(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(
            reverse("employees"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["employees"])
        first_employee = payload["employees"][0]
        self.assertIn("department_name", first_employee)
        self.assertIn("status_label", first_employee)
        self.assertIn("profile_url", first_employee)

    def test_employees_search_filters_by_name_status_and_department(self):
        matching_outsider = Employees.objects.create(
            last_name=self.employee.last_name,
            first_name=self.employee.first_name,
            middle_name="Search",
            login="matching-outsider-login",
            position="Analyst",
            date_joined=timezone.localdate(),
            annual_paid_leave_days=52,
            department=self.hr_department,
            role=Employees.ROLE_EMPLOYEE,
        )
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(
            reverse("employees"),
            {
                "search": self.employee.first_name,
                "status": "True",
                "department": self.engineering.id,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        employee_ids = {employee["id"] for employee in response.json()["employees"]}
        self.assertIn(self.employee.id, employee_ids)
        self.assertNotIn(matching_outsider.id, employee_ids)
        self.assertNotIn(self.outsider.id, employee_ids)

    def test_employees_search_respects_department_head_scope(self):
        self.client.force_login(self.department_head.user)

        response = self.client.get(
            reverse("employees"),
            {"search": self.outsider.first_name},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        employee_ids = {employee["id"] for employee in response.json()["employees"]}
        self.assertNotIn(self.outsider.id, employee_ids)

    def test_employees_page_uses_current_schedule_for_status(self):
        self.client.force_login(self.hr_employee.user)
        today = timezone.localdate()
        schedule = VacationSchedule.objects.create(
            year=today.year,
            status=VacationSchedule.STATUS_APPROVED,
            created_by=self.hr_employee,
            approved_by=self.enterprise_head,
        )
        VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=today,
            end_date=today,
            vacation_type="paid",
            chargeable_days=1,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        response = self.client.get(reverse("employees"))
        employee_row = next(employee for employee in response.context["employees"] if employee["id"] == self.employee.id)

        self.assertFalse(employee_row["is_working"])
        self.assertEqual(employee_row["status_label"], "В отпуске")
        self.assertContains(
            response,
            '<span class="employee-status-badge employee-status-badge--vacation">В отпуске</span>',
            html=True,
        )

    def test_employees_status_filter_uses_current_schedule(self):
        self.client.force_login(self.hr_employee.user)
        today = timezone.localdate()
        schedule = VacationSchedule.objects.create(
            year=today.year,
            status=VacationSchedule.STATUS_APPROVED,
            created_by=self.hr_employee,
            approved_by=self.enterprise_head,
        )
        VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=today,
            end_date=today,
            vacation_type="paid",
            chargeable_days=1,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        vacation_response = self.client.get(
            reverse("employees"),
            {"status": "False"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        working_response = self.client.get(
            reverse("employees"),
            {"status": "True"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        vacation_ids = {employee["id"] for employee in vacation_response.json()["employees"]}
        working_ids = {employee["id"] for employee in working_response.json()["employees"]}
        self.assertIn(self.employee.id, vacation_ids)
        self.assertNotIn(self.employee.id, working_ids)

    def test_authorized_person_is_hidden_from_employee_registry(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("employees"))
        ajax_response = self.client.get(reverse("employees"), HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["employees_count"], 6)
        self.assertNotIn(self.authorized_person.id, [employee["id"] for employee in response.context["employees"]])
        self.assertNotIn(self.authorized_person.id, [employee["id"] for employee in ajax_response.json()["employees"]])

    def test_employees_page_uses_bulk_leave_summary_without_n_plus_one_queries(self):
        for index in range(12):
            extra_employee = Employees.objects.create(
                last_name=f"Сотрудник{index}",
                first_name="Тест",
                middle_name="Иванович",
                login=f"bulk-employee-{index}",
                position="Специалист",
                annual_paid_leave_days=52,
                department=self.engineering,
                role=Employees.ROLE_EMPLOYEE,
            )
            sync_employee_user(extra_employee, raw_password="bulk-pass")

        self.client.force_login(self.hr_employee.user)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("employees"))

        self.assertEqual(response.status_code, 200)
        self.assertLess(len(queries), 20)
