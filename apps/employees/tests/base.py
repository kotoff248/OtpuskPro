from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.services import sync_employee_user
from apps.employees.models import Departments, Employees


class EmployeeTestCase(TestCase):
    def setUp(self):
        self.engineering = Departments.objects.create(name="Engineering")
        self.hr_department = Departments.objects.create(name="HR")
        joined_date = timezone.localdate() - timedelta(days=900)

        self.hr_employee = Employees.objects.create(
            last_name="Кадрова",
            first_name="Анна",
            middle_name="Сергеевна",
            login="hr-login",
            position="HR",
            date_joined=joined_date,
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
            date_joined=joined_date,
            annual_paid_leave_days=52,
            department=self.engineering,
            role=Employees.ROLE_DEPARTMENT_HEAD,
        )
        sync_employee_user(self.department_head, raw_password="dept-head-pass")

        self.available_department_head = Employees.objects.create(
            last_name="Запаснов",
            first_name="Алексей",
            middle_name="Сергеевич",
            login="available-head-login",
            position="Руководитель отдела",
            date_joined=joined_date,
            annual_paid_leave_days=52,
            role=Employees.ROLE_DEPARTMENT_HEAD,
        )
        sync_employee_user(self.available_department_head, raw_password="available-head-pass")

        self.enterprise_head = Employees.objects.create(
            last_name="Директорова",
            first_name="Мария",
            middle_name="Петровна",
            login="enterprise-head-login",
            position="Директор",
            date_joined=joined_date,
            annual_paid_leave_days=52,
            department=self.hr_department,
            role=Employees.ROLE_ENTERPRISE_HEAD,
        )
        sync_employee_user(self.enterprise_head, raw_password="enterprise-pass")

        self.authorized_person = Employees.objects.create(
            last_name="Админова",
            first_name="Инна",
            middle_name="Олеговна",
            login="authorized-login",
            position="Уполномоченное лицо",
            date_joined=joined_date,
            annual_paid_leave_days=52,
            role=Employees.ROLE_AUTHORIZED_PERSON,
        )
        sync_employee_user(self.authorized_person, raw_password="authorized-pass")

        self.employee = Employees.objects.create(
            last_name="Сотрудник",
            first_name="Иван",
            middle_name="Игоревич",
            login="employee-login",
            position="Специалист",
            date_joined=joined_date,
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
            date_joined=joined_date,
            annual_paid_leave_days=52,
            department=self.hr_department,
            role=Employees.ROLE_EMPLOYEE,
        )
        sync_employee_user(self.outsider, raw_password="outsider-pass")
