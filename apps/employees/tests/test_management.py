from django.urls import reverse

from apps.employees.models import Employees

from .base import EmployeeTestCase


class EmployeeMutationTests(EmployeeTestCase):
    def test_hr_can_update_employee_profile(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.post(
            reverse("update_employee", args=[self.employee.id]),
            {
                "login": "employee-updated",
                "last_name": "Обновленный",
                "first_name": "Иван",
                "middle_name": "Игоревич",
                "position": "Ведущий специалист",
                "role": Employees.ROLE_EMPLOYEE,
                "date_joined": self.employee.date_joined.isoformat(),
                "annual_paid_leave_days": 28,
                "department": self.hr_department.id,
                "password": "",
                "next_path": reverse("main"),
            },
        )

        self.employee.refresh_from_db()

        self.assertRedirects(response, reverse("main"))
        self.assertEqual(self.employee.login, "employee-updated")
        self.assertEqual(self.employee.department, self.hr_department)
        self.assertEqual(self.employee.annual_paid_leave_days, 52)

    def test_department_head_cannot_update_employee_profile(self):
        self.client.force_login(self.department_head.user)

        response = self.client.post(
            reverse("update_employee", args=[self.employee.id]),
            {
                "login": "blocked-update",
                "last_name": self.employee.last_name,
                "first_name": self.employee.first_name,
                "middle_name": self.employee.middle_name,
                "position": self.employee.position,
                "role": Employees.ROLE_EMPLOYEE,
                "date_joined": self.employee.date_joined.isoformat(),
                "annual_paid_leave_days": 52,
                "department": self.engineering.id,
                "password": "",
                "next_path": reverse("main"),
            },
        )

        self.employee.refresh_from_db()

        self.assertRedirects(response, reverse("main"))
        self.assertEqual(self.employee.login, "employee-login")

    def test_enterprise_head_cannot_update_employee_profile(self):
        self.client.force_login(self.enterprise_head.user)

        response = self.client.post(
            reverse("update_employee", args=[self.employee.id]),
            {
                "login": "blocked-update",
                "last_name": self.employee.last_name,
                "first_name": self.employee.first_name,
                "middle_name": self.employee.middle_name,
                "position": self.employee.position,
                "role": Employees.ROLE_EMPLOYEE,
                "date_joined": self.employee.date_joined.isoformat(),
                "annual_paid_leave_days": 52,
                "department": self.engineering.id,
                "password": "",
                "next_path": reverse("main"),
            },
        )

        self.employee.refresh_from_db()

        self.assertRedirects(response, reverse("main"))
        self.assertEqual(self.employee.login, "employee-login")

    def test_hr_can_soft_delete_employee_and_disable_login(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.post(reverse("delete_employee", args=[self.employee.id]))

        self.employee.refresh_from_db()
        self.engineering.refresh_from_db()
        self.assertRedirects(response, reverse("employees"))
        self.assertFalse(self.employee.is_active_employee)
        self.assertFalse(self.employee.user.is_active)

        employees_response = self.client.get(reverse("employees"))
        self.assertNotContains(employees_response, self.employee.full_name)

        departments_response = self.client.get(reverse("departments"))
        self.assertContains(departments_response, self.engineering.name)
        self.assertContains(departments_response, "1")

        self.client.logout()
        login_response = self.client.post(
            reverse("login"),
            {
                "username": "employee-login",
                "password": "employee-pass",
                "user_type": "employee",
            },
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertTrue(login_response.context["error"])

    def test_hr_can_soft_delete_department_head_and_clear_department_head_link(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.post(reverse("delete_employee", args=[self.department_head.id]))

        self.department_head.refresh_from_db()
        self.engineering.refresh_from_db()
        self.assertRedirects(response, reverse("employees"))
        self.assertFalse(self.department_head.is_active_employee)
        self.assertIsNone(self.engineering.head)

    def test_hr_cannot_delete_enterprise_head_authorized_person_or_self(self):
        self.client.force_login(self.hr_employee.user)

        enterprise_response = self.client.post(reverse("delete_employee", args=[self.enterprise_head.id]))
        authorized_response = self.client.post(reverse("delete_employee", args=[self.authorized_person.id]))
        self_response = self.client.post(reverse("delete_employee", args=[self.hr_employee.id]))

        self.enterprise_head.refresh_from_db()
        self.authorized_person.refresh_from_db()
        self.hr_employee.refresh_from_db()
        self.assertRedirects(enterprise_response, reverse("employee_profile", args=[self.enterprise_head.id]))
        self.assertEqual(authorized_response.status_code, 404)
        self.assertRedirects(self_response, reverse("employee_profile", args=[self.hr_employee.id]))
        self.assertTrue(self.enterprise_head.is_active_employee)
        self.assertTrue(self.authorized_person.is_active_employee)
        self.assertTrue(self.hr_employee.is_active_employee)

    def test_hr_cannot_view_or_update_authorized_person_profile(self):
        self.client.force_login(self.hr_employee.user)

        profile_response = self.client.get(reverse("employee_profile", args=[self.authorized_person.id]))
        update_response = self.client.post(
            reverse("update_employee", args=[self.authorized_person.id]),
            {
                "login": "admin_1",
                "last_name": "Hidden",
                "first_name": "Person",
                "middle_name": "Service",
                "position": "Service",
                "role": Employees.ROLE_AUTHORIZED_PERSON,
                "date_joined": self.authorized_person.date_joined.isoformat(),
                "annual_paid_leave_days": 52,
                "department": "",
                "password": "",
            },
        )

        self.authorized_person.refresh_from_db()
        self.assertEqual(profile_response.status_code, 404)
        self.assertEqual(update_response.status_code, 404)
        self.assertEqual(self.authorized_person.full_name, "")
        self.assertEqual(self.authorized_person.position, "")
