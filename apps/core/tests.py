from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.employees.models import Departments, Employees
from apps.leave.models import VacationRequest
from apps.leave.services import add_years_safe, get_employee_leave_summary


class SeedVacationRequestsCommandTests(TestCase):
    def test_command_rebuilds_enterprise_structure_and_credentials(self):
        stale_department = Departments.objects.create(name="Старый отдел")
        Employees.objects.create(
            login="stale_user",
            last_name="Старый",
            first_name="Сотрудник",
            middle_name="Тестович",
            position="Тестировщик",
            department=stale_department,
            role=Employees.ROLE_EMPLOYEE,
            password="legacy",
        )

        stdout = StringIO()
        call_command("seed_vacation_requests", seed_value=7, stdout=stdout)

        self.assertEqual(Departments.objects.count(), 5)
        self.assertEqual(Employees.objects.filter(role=Employees.ROLE_EMPLOYEE).count(), 100)
        self.assertEqual(Employees.objects.filter(role=Employees.ROLE_HR).count(), 2)
        self.assertEqual(Employees.objects.filter(role=Employees.ROLE_DEPARTMENT_HEAD).count(), 5)
        self.assertEqual(Employees.objects.filter(role=Employees.ROLE_ENTERPRISE_HEAD).count(), 1)
        self.assertEqual(Employees.objects.filter(role=Employees.ROLE_AUTHORIZED_PERSON).count(), 1)
        self.assertFalse(Employees.objects.filter(login="stale_user").exists())

        self.assertTrue(Employees.objects.filter(login="director_1", role=Employees.ROLE_ENTERPRISE_HEAD).exists())
        self.assertTrue(Employees.objects.filter(login="admin_1", role=Employees.ROLE_AUTHORIZED_PERSON).exists())
        self.assertTrue(Employees.objects.filter(login="hr_1", role=Employees.ROLE_HR).exists())
        self.assertTrue(Employees.objects.filter(login="manager_5", role=Employees.ROLE_DEPARTMENT_HEAD).exists())
        self.assertTrue(Employees.objects.filter(login="employ_100", role=Employees.ROLE_EMPLOYEE).exists())

        authorized_person = Employees.objects.get(login="admin_1")
        self.assertEqual(authorized_person.full_name, "")
        self.assertEqual(authorized_person.position, "")
        self.assertIsNone(authorized_person.department)
        self.assertEqual(authorized_person.vacation_days, 0)
        self.assertFalse(authorized_person.is_working)
        self.assertEqual(authorized_person.user.first_name, "")
        self.assertTrue(authorized_person.user.check_password("1234"))
        self.assertTrue(Employees.objects.get(login="hr_1").user.check_password("1234"))
        self.assertTrue(Employees.objects.get(login="manager_1").user.check_password("1234"))
        self.assertTrue(Employees.objects.get(login="employ_1").user.check_password("1234"))

        for department in Departments.objects.all():
            with self.subTest(department=department.name):
                self.assertIsNotNone(department.head)
                self.assertEqual(
                    department.employees.filter(role=Employees.ROLE_EMPLOYEE).count(),
                    20,
                )

    def test_command_generates_non_overlapping_active_vacations_and_metrics(self):
        call_command("seed_vacation_requests", seed_value=17, stdout=StringIO())

        self.assertGreater(
            VacationRequest.objects.filter(status=VacationRequest.STATUS_APPROVED).count(),
            0,
        )
        self.assertGreater(
            VacationRequest.objects.filter(status=VacationRequest.STATUS_PENDING).count(),
            0,
        )
        self.assertGreater(
            VacationRequest.objects.filter(status=VacationRequest.STATUS_REJECTED).count(),
            0,
        )

        for employee in Employees.objects.all():
            active_requests = list(
                employee.vacation_requests.filter(status__in=VacationRequest.ACTIVE_STATUSES).order_by("start_date", "end_date")
            )
            for previous, current in zip(active_requests, active_requests[1:]):
                with self.subTest(employee=employee.login, previous=previous.id, current=current.id):
                    self.assertLess(previous.end_date, current.start_date)

            self.assertGreaterEqual(employee.used_up_days, 0)
            self.assertGreaterEqual(employee.vacation_days, 0)
            self.assertIsNotNone(employee.is_working)

    def test_command_generates_realistic_available_balances(self):
        call_command("seed_vacation_requests", seed_value=23, stdout=StringIO())

        employees = list(Employees.objects.filter(role=Employees.ROLE_EMPLOYEE))
        available_days = [float(get_employee_leave_summary(employee)["available"]) for employee in employees]

        self.assertTrue(all(balance <= 104 for balance in available_days))
        self.assertGreaterEqual(sum(balance <= 60 for balance in available_days), 85)
        self.assertGreater(sum(balance <= 35 for balance in available_days), 50)

    def test_command_generates_realistic_leave_patterns_and_types(self):
        call_command("seed_vacation_requests", seed_value=31, stdout=StringIO())

        self.assertTrue(VacationRequest.objects.filter(vacation_type="unpaid").exists())
        self.assertTrue(VacationRequest.objects.filter(vacation_type="study").exists())

        today = timezone.localdate()
        employees = Employees.objects.filter(role=Employees.ROLE_EMPLOYEE)

        for employee in employees:
            approved_paid_requests = list(
                employee.vacation_requests.filter(
                    vacation_type="paid",
                    status=VacationRequest.STATUS_APPROVED,
                ).order_by("start_date", "end_date")
            )

            if (today - employee.date_joined).days >= 365:
                cursor = employee.date_joined
                while True:
                    working_year_end = add_years_safe(cursor, 1) - timedelta(days=1)
                    if working_year_end >= today:
                        break

                    year_requests = [
                        request_obj
                        for request_obj in approved_paid_requests
                        if request_obj.start_date <= working_year_end and request_obj.end_date >= cursor
                    ]
                    with self.subTest(employee=employee.login, year_start=cursor):
                        self.assertTrue(
                            any((request_obj.end_date - request_obj.start_date).days + 1 >= 14 for request_obj in year_requests)
                        )
                    cursor = working_year_end + timedelta(days=1)

            for previous, current in zip(approved_paid_requests, approved_paid_requests[1:]):
                gap_days = (current.start_date - previous.end_date).days - 1
                with self.subTest(employee=employee.login, previous=previous.id, current=current.id):
                    self.assertGreaterEqual(gap_days, 14)
