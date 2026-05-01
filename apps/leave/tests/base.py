from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.services import sync_employee_user
from apps.employees.models import Departments, EmployeePosition, Employees, ProductionGroup


class LeaveTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.engineering = Departments.objects.create(name="Engineering")
        cls.hr_department = Departments.objects.create(name="HR")
        cls.engineering_group = ProductionGroup.objects.create(department=cls.engineering, name="Инженеры")
        cls.engineering_leadership_group = ProductionGroup.objects.create(department=cls.engineering, name="Руководство отдела")
        cls.hr_group = ProductionGroup.objects.create(department=cls.hr_department, name="HR и офис")
        cls.engineering_position = EmployeePosition.objects.create(
            department=cls.engineering,
            production_group=cls.engineering_group,
            title="Специалист",
        )
        cls.engineering_engineer_position = EmployeePosition.objects.create(
            department=cls.engineering,
            production_group=cls.engineering_group,
            title="Инженер",
        )
        cls.engineering_head_position = EmployeePosition.objects.create(
            department=cls.engineering,
            production_group=cls.engineering_leadership_group,
            title="Руководитель отдела",
        )
        cls.hr_position = EmployeePosition.objects.create(
            department=cls.hr_department,
            production_group=cls.hr_group,
            title="HR",
        )
        cls.enterprise_position = EmployeePosition.objects.create(
            department=cls.hr_department,
            production_group=cls.hr_group,
            title="Директор",
        )
        cls.hr_head_position = EmployeePosition.objects.create(
            department=cls.hr_department,
            production_group=cls.hr_group,
            title="Руководитель отдела",
        )
        cls.outsider_position = EmployeePosition.objects.create(
            department=cls.hr_department,
            production_group=cls.hr_group,
            title="Аналитик",
        )

        cls.employee = Employees.objects.create(
            last_name="Календарев",
            first_name="Иван",
            middle_name="Петрович",
            login="calendar-user",
            position="Специалист",
            employee_position=cls.engineering_position,
            department=cls.engineering,
            date_joined=cls.today - timedelta(days=420),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        sync_employee_user(cls.employee, raw_password="employee-pass")

        cls.department_head = Employees.objects.create(
            last_name="Планова",
            first_name="Мария",
            middle_name="Игоревна",
            login="calendar-dept-head",
            position="Руководитель отдела",
            employee_position=cls.engineering_head_position,
            department=cls.engineering,
            date_joined=cls.today - timedelta(days=800),
            annual_paid_leave_days=52,
            role=Employees.ROLE_DEPARTMENT_HEAD,
        )
        sync_employee_user(cls.department_head, raw_password="dept-head-pass")

        cls.enterprise_head = Employees.objects.create(
            last_name="Директоров",
            first_name="Олег",
            middle_name="Игоревич",
            login="calendar-enterprise-head",
            position="Директор",
            employee_position=cls.enterprise_position,
            department=cls.hr_department,
            date_joined=cls.today - timedelta(days=900),
            annual_paid_leave_days=52,
            role=Employees.ROLE_ENTERPRISE_HEAD,
        )
        sync_employee_user(cls.enterprise_head, raw_password="enterprise-pass")

        cls.hr_employee = Employees.objects.create(
            last_name="Кадрова",
            first_name="Анна",
            middle_name="Сергеевна",
            login="calendar-hr",
            position="HR",
            employee_position=cls.hr_position,
            department=cls.hr_department,
            date_joined=cls.today - timedelta(days=700),
            annual_paid_leave_days=52,
            role=Employees.ROLE_HR,
        )
        sync_employee_user(cls.hr_employee, raw_password="hr-pass")

        cls.authorized_person = Employees.objects.create(
            last_name="Админова",
            first_name="Инна",
            middle_name="Олеговна",
            login="authorized-person",
            position="Уполномоченное лицо",
            date_joined=cls.today - timedelta(days=1000),
            annual_paid_leave_days=52,
            role=Employees.ROLE_AUTHORIZED_PERSON,
        )
        sync_employee_user(cls.authorized_person, raw_password="authorized-pass")

        cls.outsider = Employees.objects.create(
            last_name="Чужой",
            first_name="Петр",
            middle_name="Сергеевич",
            login="other-department-user",
            position="Аналитик",
            employee_position=cls.outsider_position,
            department=cls.hr_department,
            date_joined=cls.today - timedelta(days=300),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        sync_employee_user(cls.outsider, raw_password="outsider-pass")

        cls.foreign_department_head = Employees.objects.create(
            last_name="Другой",
            first_name="Роман",
            middle_name="Олегович",
            login="foreign-department-head",
            position="Руководитель отдела",
            employee_position=cls.hr_head_position,
            department=cls.hr_department,
            date_joined=cls.today - timedelta(days=850),
            annual_paid_leave_days=52,
            role=Employees.ROLE_DEPARTMENT_HEAD,
        )
        sync_employee_user(cls.foreign_department_head, raw_password="foreign-head-pass")
