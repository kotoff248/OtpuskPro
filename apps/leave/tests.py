from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.accounts.services import sync_employee_user
from apps.employees.models import Departments, Employees
from apps.leave.models import VacationRequest
from apps.leave.services import (
    approve_vacation_request,
    build_analytics_payload,
    build_calendar_base_data,
    build_calendar_rows,
    sync_employee_vacation_metrics,
)


class VacationRulesTests(TestCase):
    def setUp(self):
        self.department = Departments.objects.create(name="Calendar Department")
        self.employee = Employees.objects.create(
            last_name="Календарев",
            first_name="Иван",
            middle_name="Петрович",
            login="calendar-user",
            position="Специалист",
            department=self.department,
            vacation_days=10,
        )
        sync_employee_user(self.employee, raw_password="employee-pass")

        self.manager = Employees.objects.create(
            last_name="Планова",
            first_name="Мария",
            middle_name="Игоревна",
            login="calendar-manager",
            position="Аналитик",
            department=self.department,
            vacation_days=31,
            is_manager=True,
        )
        sync_employee_user(self.manager, raw_password="manager-pass")

    def test_rejected_request_does_not_block_new_request(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-08-11",
            end_date="2026-08-15",
            vacation_type="paid",
            status=VacationRequest.STATUS_REJECTED,
        )

        self.client.force_login(self.employee.user)
        response = self.client.post(
            reverse("calendar"),
            {
                "type_vacation": "paid",
                "start_date": "2026-08-11",
                "end_date": "2026-08-15",
                "next_view_mode": "month",
                "next_year": "2026",
                "next_month": "8",
            },
        )

        self.assertRedirects(response, f'{reverse("calendar")}?view=month&year=2026&month=8')
        self.assertEqual(
            VacationRequest.objects.filter(
                employee=self.employee,
                start_date="2026-08-11",
                end_date="2026-08-15",
            ).count(),
            2,
        )
        self.assertTrue(
            VacationRequest.objects.filter(
                employee=self.employee,
                start_date="2026-08-11",
                end_date="2026-08-15",
                status=VacationRequest.STATUS_PENDING,
            ).exists()
        )

    def test_approve_fails_when_balance_insufficient(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-07-01",
            end_date="2026-07-10",
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        sync_employee_vacation_metrics(self.employee)

        pending_request = VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-09-01",
            end_date="2026-09-03",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )

        with self.assertRaises(ValidationError):
            approve_vacation_request(pending_request.id)

    def test_approve_fails_when_dates_conflict(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-09-10",
            end_date="2026-09-12",
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        pending_request = VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-09-11",
            end_date="2026-09-13",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )

        with self.assertRaises(ValidationError):
            approve_vacation_request(pending_request.id)

    def test_unpaid_vacation_does_not_reduce_balance(self):
        request_obj = VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-10-01",
            end_date="2026-10-05",
            vacation_type="unpaid",
            status=VacationRequest.STATUS_APPROVED,
        )
        sync_employee_vacation_metrics(self.employee)
        self.employee.refresh_from_db()

        self.assertEqual(request_obj.vacation_type, "unpaid")
        self.assertEqual(self.employee.used_up_days, 0)

    def test_applications_ajax_returns_structured_json(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-11-01",
            end_date="2026-11-03",
            vacation_type="study",
            status=VacationRequest.STATUS_PENDING,
        )
        self.client.force_login(self.manager.user)
        response = self.client.get(
            reverse("applications"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("vacations", payload)
        self.assertNotIn("html", payload)
        self.assertEqual(payload["vacations"][0]["employee_name"], "Календарев Иван Петрович")

    def test_analytics_split_duration_by_month_overlap(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date=date(2026, 1, 30),
            end_date=date(2026, 2, 2),
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )

        payload = build_analytics_payload()

        self.assertEqual(payload["values1"][0], 1)
        self.assertEqual(payload["values1"][1], 1)
        self.assertEqual(payload["values2"][0], 2)
        self.assertEqual(payload["values2"][1], 2)
        self.assertEqual(payload["values3"][0], 2)
        self.assertEqual(payload["values3"][1], 2)

    def test_manager_views_render_successfully(self):
        request_obj = VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-12-01",
            end_date="2026-12-02",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        self.client.force_login(self.manager.user)

        urls = (
            reverse("calendar"),
            reverse("applications"),
            reverse("analytics"),
            reverse("vacation_detail", args=[request_obj.id]),
        )

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_calendar_page_uses_shared_vacation_modal_hooks(self):
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("calendar"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-modal-open="vacation-modal"')
        self.assertContains(response, 'id="vacation-modal"')
        self.assertContains(response, 'class="app-modal"')
        self.assertContains(response, 'data-modal-close')
        self.assertContains(response, 'data-date-field')

    def test_calendar_page_renders_summary_cards_with_values(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-11-01",
            end_date="2026-11-03",
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("calendar"), {"view": "month", "year": 2026, "month": 11})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Сотрудников в периоде")
        self.assertContains(response, "Одобрено дней")
        self.assertContains(response, "В ожидании дней")
        self.assertContains(response, '<strong class="calendar-summary-card__value">1</strong>', html=True)
        self.assertContains(response, '<strong class="calendar-summary-card__value">3</strong>', html=True)

    def test_calendar_page_uses_shared_employee_detail_modal_shell(self):
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("calendar"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="calendar-detail-drawer"')
        self.assertContains(response, 'class="app-modal app-modal--drawer"')
        self.assertContains(response, 'app-modal__dialog app-modal__dialog--drawer')
        self.assertContains(response, 'id="calendar-detail-name"')
        self.assertContains(response, 'id="calendar-selected-list"')
        self.assertContains(response, 'id="calendar-year-list"')
        self.assertContains(response, 'data-modal-close')
        self.assertNotContains(response, 'data-close-drawer')

    def test_calendar_year_view_renders_sticky_header_structure(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-03-10",
            end_date="2026-03-12",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("calendar"), {"view": "year", "year": 2026})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="year-grid year-grid--header"')
        self.assertContains(response, 'class="timeline-head timeline-head--employee year-head year-head--employee"')
        self.assertContains(response, 'class="timeline-employee-card year-employee-card"')
        self.assertContains(response, 'timeline-employee-card__badge')
        self.assertContains(response, 'status-count status-count--pending')
        self.assertContains(response, 'data-employee-id=')

    def test_year_view_segments_follow_real_dates_across_month_boundary(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-03-19",
            end_date="2026-04-01",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )

        employees, employee_day_status, employee_entries = build_calendar_base_data(2026)
        rows, _ = build_calendar_rows(
            employees,
            employee_day_status,
            employee_entries,
            year=2026,
            month=3,
            view_mode="year",
            today=date(2026, 3, 1),
        )

        row = next(row for row in rows if row["employee_id"] == self.employee.id)
        march_cell = row["cells"][2]
        april_cell = row["cells"][3]

        self.assertEqual(march_cell["pending_days"], 13)
        self.assertEqual(len(march_cell["segments"]), 1)
        self.assertEqual(march_cell["segments"][0]["offset_percent"], 58.1)
        self.assertEqual(march_cell["segments"][0]["width_percent"], 41.9)
        self.assertEqual(april_cell["pending_days"], 1)
        self.assertEqual(len(april_cell["segments"]), 1)
        self.assertEqual(april_cell["segments"][0]["offset_percent"], 0.0)
        self.assertEqual(april_cell["segments"][0]["width_percent"], 3.3)

    def test_year_view_keeps_multiple_intervals_in_same_month(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-03-01",
            end_date="2026-03-03",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-03-10",
            end_date="2026-03-12",
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )

        employees, employee_day_status, employee_entries = build_calendar_base_data(2026)
        rows, _ = build_calendar_rows(
            employees,
            employee_day_status,
            employee_entries,
            year=2026,
            month=3,
            view_mode="year",
            today=date(2026, 3, 1),
        )

        row = next(row for row in rows if row["employee_id"] == self.employee.id)
        march_cell = row["cells"][2]

        self.assertEqual(march_cell["status"], "mixed")
        self.assertEqual(march_cell["approved_days"], 3)
        self.assertEqual(march_cell["pending_days"], 3)
        self.assertEqual(len(march_cell["segments"]), 2)
        self.assertEqual(march_cell["segments"][0]["status"], VacationRequest.STATUS_PENDING)
        self.assertEqual(march_cell["segments"][0]["offset_percent"], 0.0)
        self.assertEqual(march_cell["segments"][1]["status"], VacationRequest.STATUS_APPROVED)
        self.assertEqual(march_cell["segments"][1]["offset_percent"], 29.0)

    def test_year_view_track_uses_css_decimal_dots(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-03-19",
            end_date="2026-04-01",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("calendar"), {"view": "year", "year": 2026})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "left: 58.1%; width: 41.9%;")
        self.assertNotContains(response, "left: 58,1%; width: 41,9%;")

    def test_year_view_empty_month_does_not_render_dash(self):
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("calendar"), {"view": "year", "year": 2026})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<span>Янв</span>")
        self.assertNotContains(response, "&mdash;")
