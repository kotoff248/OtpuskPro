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
            role=Employees.ROLE_EMPLOYEE,
        )
        sync_employee_user(self.employee, raw_password="employee-pass")

        self.hr = Employees.objects.create(
            last_name="Петрова",
            first_name="Анна",
            middle_name="Сергеевна",
            login="hr-user",
            position="HR",
            department=self.department,
            role=Employees.ROLE_HR,
        )
        sync_employee_user(self.hr, raw_password="hr-pass")

    def test_employee_can_login_with_employee_contour(self):
        response = self.client.post(
            reverse("login"),
            {
                "username": "ivan",
                "password": "employee-pass",
                "user_type": "employee",
            },
        )

        self.assertRedirects(response, reverse("main"))

    def test_employee_cannot_login_with_management_contour(self):
        response = self.client.post(
            reverse("login"),
            {
                "username": "ivan",
                "password": "employee-pass",
                "user_type": "management",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["error"])

    def test_management_user_can_login_with_management_contour(self):
        response = self.client.post(
            reverse("login"),
            {
                "username": "hr-user",
                "password": "hr-pass",
                "user_type": "management",
            },
        )

        self.assertRedirects(response, reverse("main"))

    def test_management_user_cannot_login_with_employee_contour(self):
        response = self.client.post(
            reverse("login"),
            {
                "username": "hr-user",
                "password": "hr-pass",
                "user_type": "employee",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["error"])

    def test_name_change_does_not_break_login(self):
        self.employee.last_name = "Петров"
        self.employee.save(update_fields=["last_name"])

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
