from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


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
