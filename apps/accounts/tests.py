from django.test import TestCase
from django.urls import reverse

from apps.accounts.services import sync_employee_user
from apps.employees.models import Departments, Employees


class LoginFlowTests(TestCase):
    def setUp(self):
        self.department = Departments.objects.create(name="IT")
        self.employee = Employees.objects.create(
            last_name="Иванов",
            first_name="Иван",
            middle_name="Иванович",
            login="ivan",
            position="Разработчик",
            department=self.department,
            vacation_days=28,
        )
        sync_employee_user(self.employee, raw_password="employee-pass")

    def test_employee_can_login_with_login(self):
        response = self.client.post(
            reverse("login"),
            {
                "username": "ivan",
                "password": "employee-pass",
                "user_type": "employee",
            },
        )

        self.assertRedirects(response, reverse("main"))

    def test_name_change_does_not_break_login(self):
        self.employee.last_name = "Петров"
        self.employee.first_name = "Иван"
        self.employee.middle_name = "Иванович"
        self.employee.save(update_fields=["last_name", "first_name", "middle_name"])

        response = self.client.post(
            reverse("login"),
            {
                "username": "ivan",
                "password": "employee-pass",
                "user_type": "employee",
            },
        )

        self.assertRedirects(response, reverse("main"))

    def test_login_page_renders_successfully(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "login.html")
