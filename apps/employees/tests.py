from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from apps.accounts.services import sync_employee_user
from apps.employees.forms import EmployeeCreateForm
from apps.employees.models import Departments, Employees


class EmployeeManagementTests(TestCase):
    def setUp(self):
        self.department = Departments.objects.create(name="Engineering")
        self.other_department = Departments.objects.create(name="HR")

        self.manager_employee = Employees.objects.create(
            last_name="Менеджер",
            first_name="Мария",
            middle_name="Петровна",
            login="manager-login",
            position="Руководитель",
            vacation_days=31,
            department=self.department,
            is_manager=True,
        )
        sync_employee_user(self.manager_employee, raw_password="manager-pass")

        self.employee = Employees.objects.create(
            last_name="Сотрудник",
            first_name="Иван",
            middle_name="Игоревич",
            login="employee-login",
            position="Специалист",
            vacation_days=28,
            department=self.department,
        )
        sync_employee_user(self.employee, raw_password="employee-pass")

    def test_duplicate_login_is_rejected(self):
        form = EmployeeCreateForm(
            data={
                "login": "employee-login",
                "last_name": "Новый",
                "first_name": "Сотрудник",
                "middle_name": "Андреевич",
                "position": "Аналитик",
                "date_joined": "2026-01-01",
                "vacation_days": 21,
                "department": self.department.id,
                "is_manager": False,
                "password": "new-user-pass",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("login", form.errors)

    def test_employee_full_name_property(self):
        self.assertEqual(self.employee.full_name, "Сотрудник Иван Игоревич")

    def test_employee_cannot_update_another_profile(self):
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("employee_profile", args=[self.manager_employee.id]))

        self.assertRedirects(response, reverse("main"))

    def test_manager_can_update_employee_profile(self):
        self.client.force_login(self.manager_employee.user)

        response = self.client.post(
            reverse("update_employee", args=[self.employee.id]),
            {
                "login": "employee-updated",
                "last_name": "Обновлённый",
                "first_name": "Иван",
                "middle_name": "Игоревич",
                "position": "Ведущий специалист",
                "date_joined": self.employee.date_joined.isoformat(),
                "vacation_days": self.employee.vacation_days,
                "department": self.other_department.id,
                "is_manager": "on",
                "password": "",
                "next_path": reverse("main"),
            },
        )

        self.employee.refresh_from_db()

        self.assertRedirects(response, reverse("main"))
        self.assertEqual(self.employee.login, "employee-updated")
        self.assertEqual(self.employee.last_name, "Обновлённый")
        self.assertEqual(self.employee.department, self.other_department)
        self.assertTrue(self.employee.is_manager)

    def test_main_page_uses_dedicated_template(self):
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("main"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "main.html")

    def test_employee_profile_renders_for_regular_employee(self):
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("employee_profile", args=[self.employee.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="employee-edit-modal"')

    def test_employee_profile_renders_for_manager_with_edit_modal(self):
        self.client.force_login(self.manager_employee.user)

        response = self.client.get(reverse("employee_profile", args=[self.employee.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="employee-edit-modal"')
        self.assertContains(response, 'class="app-modal"')
        self.assertContains(response, 'name="next_path"')

    def test_employees_page_uses_shared_create_modal_shell(self):
        self.client.force_login(self.manager_employee.user)

        response = self.client.get(reverse("employees"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="employee-create-modal"')
        self.assertContains(response, 'class="app-modal"')
        self.assertContains(response, 'data-modal-open="employee-create-modal"')
        self.assertContains(response, 'name="employee_last_name"')
        self.assertContains(response, 'name="employee_first_name"')
        self.assertContains(response, 'name="employee_middle_name"')
        self.assertContains(response, 'data-date-field')
        self.assertContains(response, 'data-employee-create-submit disabled')

    def test_manager_pages_render_successfully(self):
        self.client.force_login(self.manager_employee.user)

        for url_name in ("employees", "departments"):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)


class EmployeeNameMigrationTests(TransactionTestCase):
    migrate_from = ("employees", "0002_alter_departments_options_alter_employees_options_and_more")
    migrate_to = ("employees", "0003_split_employee_name")

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        self.old_apps = self.executor.loader.project_state([self.migrate_from]).apps

    def migrate_forwards(self):
        self.executor.loader.build_graph()
        self.executor.migrate([self.migrate_to])
        return self.executor.loader.project_state([self.migrate_to]).apps

    def test_migration_splits_existing_name(self):
        Departments = self.old_apps.get_model("employees", "Departments")
        Employees = self.old_apps.get_model("employees", "Employees")

        department = Departments.objects.create(name="Migration Department")
        employee = Employees.objects.create(
            name="Иван Иванович Петров",
            login="migration-user",
            position="Аналитик",
            vacation_days=28,
            department=department,
        )

        new_apps = self.migrate_forwards()
        NewEmployees = new_apps.get_model("employees", "Employees")
        migrated_employee = NewEmployees.objects.get(pk=employee.pk)

        self.assertEqual(migrated_employee.last_name, "Иван")
        self.assertEqual(migrated_employee.first_name, "Иванович")
        self.assertEqual(migrated_employee.middle_name, "Петров")
