from datetime import date, timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.employees.models import Departments, Employees
from apps.leave.models import (
    DepartmentStaffingRule,
    DepartmentWorkload,
    VacationPreference,
    VacationRequest,
    VacationSchedule,
    VacationScheduleAuthorizedApproval,
    VacationScheduleChangeRequest,
    VacationScheduleDepartmentApproval,
    VacationScheduleEnterpriseApproval,
    VacationScheduleItem,
)
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
        self.assertEqual(VacationSchedule.objects.filter(year__range=(2011, 2025)).count(), 15)
        self.assertFalse(VacationSchedule.objects.filter(year=2026).exists())
        self.assertEqual(DepartmentStaffingRule.objects.count(), 5)
        self.assertEqual(DepartmentWorkload.objects.count(), 5 * 15 * 12)

        for department in Departments.objects.all():
            with self.subTest(department=department.name):
                self.assertIsNotNone(department.head)
                self.assertEqual(
                    department.employees.filter(role=Employees.ROLE_EMPLOYEE).count(),
                    20,
                )

    def test_command_generates_non_overlapping_active_vacations_and_metrics(self):
        call_command("seed_vacation_requests", seed_value=17, stdout=StringIO())

        self.assertGreater(VacationScheduleItem.objects.filter(status=VacationScheduleItem.STATUS_APPROVED).count(), 0)
        self.assertFalse(
            VacationRequest.objects.filter(
                vacation_type="paid",
                status__in=[VacationRequest.STATUS_APPROVED, VacationRequest.STATUS_PENDING],
            ).exists()
        )
        self.assertGreater(
            VacationRequest.objects.filter(status=VacationRequest.STATUS_REJECTED).count(),
            0,
        )

        for employee in Employees.objects.all():
            active_periods = list(
                employee.vacation_requests.filter(status__in=VacationRequest.ACTIVE_STATUSES).values_list("start_date", "end_date")
            )
            active_periods.extend(
                employee.vacation_schedule_items.filter(
                    status__in=VacationScheduleItem.ACTIVE_STATUSES,
                ).values_list("start_date", "end_date")
            )
            active_periods = sorted(active_periods)
            for previous, current in zip(active_periods, active_periods[1:]):
                with self.subTest(employee=employee.login, previous=previous, current=current):
                    self.assertLess(previous[1], current[0])

            self.assertGreaterEqual(employee.used_up_days, 0)
            self.assertGreaterEqual(employee.vacation_days, 0)
            self.assertIsNotNone(employee.is_working)

    def test_command_generates_realistic_available_balances(self):
        call_command("seed_vacation_requests", seed_value=23, stdout=StringIO())

        employees = list(Employees.objects.filter(role=Employees.ROLE_EMPLOYEE))
        available_days = [float(get_employee_leave_summary(employee)["available"]) for employee in employees]

        self.assertTrue(all(balance <= 104 for balance in available_days))
        self.assertGreaterEqual(sum(35 <= balance <= 60 for balance in available_days), 80)
        self.assertGreater(sum(balance >= 45 for balance in available_days), 70)

    def test_command_generates_realistic_leave_patterns_and_types(self):
        call_command("seed_vacation_requests", seed_value=31, stdout=StringIO())

        self.assertTrue(VacationRequest.objects.filter(vacation_type="unpaid").exists())
        self.assertTrue(VacationRequest.objects.filter(vacation_type="study").exists())
        self.assertTrue(VacationPreference.objects.filter(status=VacationPreference.STATUS_FILLED).exists())
        self.assertTrue(VacationScheduleDepartmentApproval.objects.filter(status=VacationScheduleDepartmentApproval.STATUS_APPROVED).exists())
        self.assertTrue(VacationScheduleEnterpriseApproval.objects.filter(status=VacationScheduleEnterpriseApproval.STATUS_APPROVED).exists())
        self.assertTrue(VacationScheduleAuthorizedApproval.objects.filter(status=VacationScheduleAuthorizedApproval.STATUS_APPROVED).exists())
        self.assertTrue(VacationScheduleChangeRequest.objects.filter(status=VacationScheduleChangeRequest.STATUS_APPROVED).exists())
        self.assertTrue(VacationScheduleChangeRequest.objects.filter(status=VacationScheduleChangeRequest.STATUS_REJECTED).exists())

        today = timezone.localdate()
        employees = Employees.objects.filter(role=Employees.ROLE_EMPLOYEE)

        for employee in employees:
            approved_paid_items = list(
                employee.vacation_schedule_items.filter(
                    vacation_type="paid",
                    status__in=VacationScheduleItem.BALANCE_STATUSES,
                ).order_by("start_date", "end_date")
            )

            if (today - employee.date_joined).days >= 365:
                cursor = employee.date_joined
                while True:
                    working_year_end = add_years_safe(cursor, 1) - timedelta(days=1)
                    if working_year_end >= today:
                        break

                    year_items = [
                        item
                        for item in approved_paid_items
                        if item.start_date <= min(working_year_end, date(2025, 12, 31)) and item.end_date >= cursor
                    ]
                    with self.subTest(employee=employee.login, year_start=cursor):
                        if cursor.year <= 2025:
                            self.assertTrue(any((item.end_date - item.start_date).days + 1 >= 14 for item in year_items))
                    cursor = working_year_end + timedelta(days=1)

            for previous, current in zip(approved_paid_items, approved_paid_items[1:]):
                with self.subTest(employee=employee.login, previous=previous.id, current=current.id):
                    self.assertLess(previous.end_date, current.start_date)
