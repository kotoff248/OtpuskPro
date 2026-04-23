from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.services import sync_employee_user
from apps.employees.forms import EmployeeCreateForm
from apps.employees.models import Departments, Employees
from apps.leave.models import VacationRequest


class EmployeeManagementTests(TestCase):
    def setUp(self):
        self.engineering = Departments.objects.create(name="Engineering")
        self.hr_department = Departments.objects.create(name="HR")

        self.hr_employee = Employees.objects.create(
            last_name="Кадрова",
            first_name="Анна",
            middle_name="Сергеевна",
            login="hr-login",
            position="HR",
            annual_paid_leave_days=52,
            department=self.hr_department,
            role=Employees.ROLE_HR,
        )
        sync_employee_user(self.hr_employee, raw_password="hr-pass")

        self.department_head = Employees.objects.create(
            last_name="Руководов",
            first_name="Павел",
            middle_name="Игоревич",
            login="dept-head-login",
            position="Руководитель отдела",
            annual_paid_leave_days=52,
            department=self.engineering,
            role=Employees.ROLE_DEPARTMENT_HEAD,
        )
        sync_employee_user(self.department_head, raw_password="dept-head-pass")

        self.enterprise_head = Employees.objects.create(
            last_name="Директорова",
            first_name="Мария",
            middle_name="Петровна",
            login="enterprise-head-login",
            position="Директор",
            annual_paid_leave_days=52,
            department=self.hr_department,
            role=Employees.ROLE_ENTERPRISE_HEAD,
        )
        sync_employee_user(self.enterprise_head, raw_password="enterprise-pass")

        self.employee = Employees.objects.create(
            last_name="Сотрудник",
            first_name="Иван",
            middle_name="Игоревич",
            login="employee-login",
            position="Специалист",
            annual_paid_leave_days=52,
            department=self.engineering,
            role=Employees.ROLE_EMPLOYEE,
        )
        sync_employee_user(self.employee, raw_password="employee-pass")

        self.outsider = Employees.objects.create(
            last_name="Чужой",
            first_name="Олег",
            middle_name="Петрович",
            login="outsider-login",
            position="Аналитик",
            annual_paid_leave_days=52,
            department=self.hr_department,
            role=Employees.ROLE_EMPLOYEE,
        )
        sync_employee_user(self.outsider, raw_password="outsider-pass")

    def test_duplicate_login_is_rejected(self):
        form = EmployeeCreateForm(
            data={
                "login": "employee-login",
                "last_name": "Новый",
                "first_name": "Сотрудник",
                "middle_name": "Андреевич",
                "position": "Аналитик",
                "date_joined": "2026-01-01",
                "annual_paid_leave_days": 52,
                "department": self.engineering.id,
                "role": Employees.ROLE_EMPLOYEE,
                "password": "new-user-pass",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("login", form.errors)

    def test_employee_full_name_property(self):
        self.assertEqual(self.employee.full_name, "Сотрудник Иван Игоревич")

    def test_department_head_is_linked_to_department(self):
        self.engineering.refresh_from_db()
        self.assertEqual(self.engineering.head, self.department_head)

    def test_employee_cannot_view_another_profile(self):
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("employee_profile", args=[self.department_head.id]))

        self.assertRedirects(response, reverse("main"))

    def test_department_head_can_view_only_own_department_profile(self):
        self.client.force_login(self.department_head.user)

        own_department_response = self.client.get(reverse("employee_profile", args=[self.employee.id]))
        foreign_department_response = self.client.get(reverse("employee_profile", args=[self.outsider.id]))

        self.assertEqual(own_department_response.status_code, 200)
        self.assertRedirects(foreign_department_response, reverse("main"))

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
                "annual_paid_leave_days": 52,
                "department": self.hr_department.id,
                "password": "",
                "next_path": reverse("main"),
            },
        )

        self.employee.refresh_from_db()

        self.assertRedirects(response, reverse("main"))
        self.assertEqual(self.employee.login, "employee-updated")
        self.assertEqual(self.employee.department, self.hr_department)

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

    def test_main_page_uses_dedicated_template_for_regular_employee(self):
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("main"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "main.html")
        self.assertNotContains(response, 'data-modal-open="employee-edit-modal"')
        self.assertNotContains(response, 'id="employee-edit-modal"')
        self.assertContains(response, "js/employee-form.js")
        self.assertNotContains(response, "js/employees-page.js")
        self.assertContains(response, "Доступно к заявке", count=1)
        self.assertContains(response, "Можно запланировать сейчас")
        self.assertNotContains(response, "page-hero__chip")
        self.assertContains(response, "Начислено по стажу")
        self.assertContains(response, "Можно запланировать сейчас")

    def test_hr_main_page_renders_with_edit_modal(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("main"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-modal-open="employee-edit-modal"')
        self.assertContains(response, 'id="employee-edit-modal"')
        self.assertContains(response, 'name="role"')
        self.assertContains(response, 'data-employee-form')
        self.assertContains(response, 'data-employee-submit')

    def test_employee_profile_renders_with_edit_modal_for_hr(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("employee_profile", args=[self.employee.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="employee-edit-modal"')
        self.assertContains(response, 'name="role"')
        self.assertContains(response, 'app-modal__dialog app-modal__dialog--employee')
        self.assertContains(response, "Доступно к заявке", count=1)
        self.assertContains(response, "Начислено по стажу")

    def test_enterprise_head_can_view_profile_without_edit_modal(self):
        self.client.force_login(self.enterprise_head.user)

        response = self.client.get(reverse("employee_profile", args=[self.employee.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="employee-edit-modal"')

    def test_main_page_renders_requests_as_cards_without_table_header(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-08-10",
            end_date="2026-08-15",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("main"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="vacation-request-card is-clickable"')
        self.assertContains(response, "Дата начала")
        self.assertContains(response, "Дата окончания")
        self.assertContains(response, "Тип отпуска")
        self.assertContains(response, "Статус")
        self.assertNotContains(response, "<thead>", html=False)

    def test_main_page_empty_requests_state_does_not_render_table_markup(self):
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("main"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Заявок на отпуск пока нет.")
        self.assertNotContains(response, "<table", html=False)

    def test_employees_page_uses_shared_create_modal_shell_for_hr(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("employees"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="employee-create-modal"')
        self.assertContains(response, 'data-modal-open="employee-create-modal"')
        self.assertContains(response, 'name="role"')
        self.assertContains(response, 'data-employee-submit disabled')
        self.assertContains(response, "js/employee-form.js")
        self.assertContains(response, "js/employees-page.js")

    def test_department_head_sees_only_managed_department_on_employees_page(self):
        self.client.force_login(self.department_head.user)

        response = self.client.get(reverse("employees"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.employee.full_name)
        self.assertNotContains(response, self.outsider.full_name)
        self.assertNotContains(response, 'employee-create-modal')

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
        self.assertLess(len(queries), 60)

    def test_departments_page_is_scoped_for_department_head(self):
        self.client.force_login(self.department_head.user)

        response = self.client.get(reverse("departments"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.engineering.name)
        self.assertContains(response, self.department_head.full_name)
        self.assertNotContains(response, self.hr_department.name)

    def test_hr_and_enterprise_head_can_view_all_departments(self):
        for actor in (self.hr_employee, self.enterprise_head):
            self.client.force_login(actor.user)
            response = self.client.get(reverse("departments"))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, self.engineering.name)
            self.assertContains(response, self.hr_department.name)


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
