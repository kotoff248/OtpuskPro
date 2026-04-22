from django.test import TestCase
from django.urls import reverse

from .models import Departments, Employees, VacationRequest
from .views import sync_employee_user


class UpdateEmployeePermissionsTests(TestCase):
    def setUp(self):
        self.department = Departments.objects.create(name='IT')
        self.other_department = Departments.objects.create(name='HR')

        self.employee = Employees.objects.create(
            name='Иван Иванов',
            position='Разработчик',
            department=self.department,
            vacation_days=28,
            password='temp',
        )
        sync_employee_user(self.employee, raw_password='employee-pass')

        self.other_employee = Employees.objects.create(
            name='Петр Петров',
            position='Аналитик',
            department=self.department,
            vacation_days=24,
            password='temp',
        )
        sync_employee_user(self.other_employee, raw_password='other-pass')

        self.manager = Employees.objects.create(
            name='Мария Смирнова',
            position='Руководитель отдела',
            department=self.department,
            vacation_days=30,
            password='temp',
            is_manager=True,
        )
        sync_employee_user(self.manager, raw_password='manager-pass')

    def test_employee_cannot_update_own_profile(self):
        self.client.force_login(self.employee.user)
        response = self.client.post(
            reverse('update_employee', args=[self.employee.id]),
            {
                'employee_name': 'Иван Обновленный',
                'employee_position': 'Старший разработчик',
                'employee_date_joined': '2024-01-10',
                'employee_password': 'new-employee-pass',
                'employee_vacation_days': '99',
                'employee_department': str(self.other_department.id),
                'employee_is_manager': 'on',
                'next_path': reverse('main'),
            },
        )

        self.employee.refresh_from_db()
        self.assertRedirects(response, reverse('main'))
        self.assertEqual(self.employee.name, 'Иван Иванов')
        self.assertEqual(self.employee.position, 'Разработчик')
        self.assertEqual(self.employee.vacation_days, 28)
        self.assertEqual(self.employee.department, self.department)
        self.assertFalse(self.employee.is_manager)
        self.assertTrue(self.employee.user.check_password('employee-pass'))

    def test_manager_can_update_other_employee_with_manager_fields(self):
        self.client.force_login(self.manager.user)
        response = self.client.post(
            reverse('update_employee', args=[self.other_employee.id]),
            {
                'employee_name': 'Петр Руководителем',
                'employee_position': 'Ведущий аналитик',
                'employee_date_joined': '2023-06-15',
                'employee_vacation_days': '31',
                'employee_department': str(self.other_department.id),
                'employee_is_manager': 'on',
                'next_path': reverse('employee_profile', args=[self.other_employee.id]),
            },
        )

        self.other_employee.refresh_from_db()
        self.assertRedirects(response, reverse('employee_profile', args=[self.other_employee.id]))
        self.assertEqual(self.other_employee.department, self.other_department)
        self.assertTrue(self.other_employee.is_manager)


class EmployeesListInteractionTests(TestCase):
    def setUp(self):
        self.department = Departments.objects.create(name='Operations')
        self.employee = Employees.objects.create(
            name='Сотрудник',
            position='Специалист',
            department=self.department,
            vacation_days=28,
            password='temp',
        )
        sync_employee_user(self.employee, raw_password='employee-pass')

        self.manager = Employees.objects.create(
            name='Руководитель',
            position='Начальник отдела',
            department=self.department,
            vacation_days=28,
            password='temp',
            is_manager=True,
        )
        sync_employee_user(self.manager, raw_password='manager-pass')

    def test_employee_sees_list_without_clickable_profile_rows(self):
        self.client.force_login(self.employee.user)
        response = self.client.get(reverse('employees'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'data-url=')
        self.assertNotContains(response, 'employee-row-clickable')

    def test_manager_sees_clickable_profile_rows(self):
        self.client.force_login(self.manager.user)
        response = self.client.get(reverse('employees'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'employee-row-clickable')


class VacationRequestFlowTests(TestCase):
    def setUp(self):
        self.department = Departments.objects.create(name='Calendar Department')
        self.employee = Employees.objects.create(
            name='Иван Календарев',
            position='Специалист',
            department=self.department,
            vacation_days=28,
            password='temp',
        )
        sync_employee_user(self.employee, raw_password='employee-pass')

        self.manager = Employees.objects.create(
            name='Мария Планова',
            position='Аналитик',
            department=self.department,
            vacation_days=31,
            password='temp',
            is_manager=True,
        )
        sync_employee_user(self.manager, raw_password='manager-pass')

        self.approved_request = VacationRequest.objects.create(
            employee=self.manager,
            start_date='2026-05-10',
            end_date='2026-05-16',
            vacation_type='paid',
            status='approved',
        )

    def test_calendar_page_renders_new_layout(self):
        self.client.force_login(self.employee.user)
        response = self.client.get(reverse('calendar'), {'year': 2026, 'view': 'year'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'calendar-board-card')
        self.assertContains(response, 'calendar-detail-card')

    def test_calendar_post_creates_pending_request(self):
        self.client.force_login(self.employee.user)
        response = self.client.post(
            reverse('calendar'),
            {
                'type_vacation': 'paid',
                'start_date': '2026-08-11',
                'end_date': '2026-08-15',
                'next_view_mode': 'month',
                'next_year': '2026',
                'next_month': '8',
            },
        )

        self.assertRedirects(response, f'{reverse("calendar")}?view=month&year=2026&month=8')
        self.assertTrue(
            VacationRequest.objects.filter(
                employee=self.employee,
                start_date='2026-08-11',
                end_date='2026-08-15',
                status='pending',
            ).exists()
        )

    def test_manager_can_approve_pending_request(self):
        pending_request = VacationRequest.objects.create(
            employee=self.employee,
            start_date='2026-09-01',
            end_date='2026-09-05',
            vacation_type='paid',
            status='pending',
        )
        self.client.force_login(self.manager.user)
        response = self.client.post(reverse('approve_vacation', args=[pending_request.id]))

        pending_request.refresh_from_db()
        self.employee.refresh_from_db()
        self.assertRedirects(response, reverse('applications'))
        self.assertEqual(pending_request.status, 'approved')
        self.assertEqual(self.employee.used_up_days, 5)

    def test_pending_requests_counter_uses_unified_model(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date='2026-11-01',
            end_date='2026-11-03',
            vacation_type='study',
            status='pending',
        )
        self.client.force_login(self.manager.user)
        response = self.client.get(reverse('main'))
        self.assertContains(response, 'message-count')
