from datetime import date

from django.urls import reverse

from apps.leave.models import DepartmentWorkload, VacationPreference, VacationRequest, VacationSchedule, VacationScheduleItem
from apps.leave.services.analytics import build_analytics_payload

from .base import LeaveTestCase


class LeaveAnalyticsTests(LeaveTestCase):
    def test_department_head_analytics_are_limited_to_own_department(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date=date(2026, 1, 30),
            end_date=date(2026, 2, 2),
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        VacationRequest.objects.create(
            employee=self.outsider,
            start_date=date(2026, 1, 10),
            end_date=date(2026, 1, 12),
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        self.client.force_login(self.department_head.user)

        response = self.client.get(reverse("analytics"))

        self.assertEqual(response.status_code, 200)
        row_employee_ids = {row["employee_id"] for row in response.context["rows"]}
        self.assertIn(self.employee.id, row_employee_ids)
        self.assertNotIn(self.outsider.id, row_employee_ids)

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

    def test_analytics_department_filter_scopes_dashboard(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date=date(2026, 4, 10),
            end_date=date(2026, 4, 14),
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        VacationRequest.objects.create(
            employee=self.outsider,
            start_date=date(2026, 4, 10),
            end_date=date(2026, 4, 14),
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        self.client.force_login(self.enterprise_head.user)

        response = self.client.get(
            reverse("analytics"),
            {"department": self.engineering.id, "year": 2026},
        )

        self.assertEqual(response.status_code, 200)
        row_employee_ids = {row["employee_id"] for row in response.context["rows"]}
        heatmap_departments = {row["department_name"] for row in response.context["department_heatmap"]}
        self.assertIn(self.employee.id, row_employee_ids)
        self.assertNotIn(self.outsider.id, row_employee_ids)
        self.assertEqual(response.context["analytics_filters"]["selected_department"], str(self.engineering.id))
        self.assertEqual(heatmap_departments, {"Engineering"})
        self.assertContains(response, "data-schedule-status-tooltip")
        self.assertContains(response, 'data-tooltip-title="Норма"')
        self.assertContains(response, 'data-tooltip-title="Доступно"')
        self.assertContains(response, 'data-tooltip-title="Готовность предпочтений"')

    def test_analytics_payload_contains_planning_dashboard_sections(self):
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            created_by=self.enterprise_head,
            approved_by=self.enterprise_head,
        )
        VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2026, 3, 3),
            end_date=date(2026, 3, 10),
            vacation_type="paid",
            chargeable_days=8,
            status=VacationScheduleItem.STATUS_APPROVED,
            risk_level=VacationScheduleItem.RISK_HIGH,
            risk_score=82,
        )
        DepartmentWorkload.objects.create(
            department=self.engineering,
            year=2026,
            month=3,
            load_level=5,
            min_staff_required=1,
            max_absent=1,
        )
        VacationPreference.objects.create(
            employee=self.employee,
            year=2026,
            start_date=date(2026, 3, 3),
            end_date=date(2026, 3, 10),
            status=VacationPreference.STATUS_FILLED,
        )

        payload = build_analytics_payload(employee_ids=[self.employee.id, self.department_head.id], year=2026)

        self.assertIn("planning_kpis", payload)
        self.assertIn("department_heatmap", payload)
        self.assertIn("analytics_chart_payload", payload)
        self.assertEqual(len(payload["monthly_metrics"]), 12)
        self.assertEqual(payload["monthly_metrics"][2]["schedule_days"], 8)
        self.assertEqual(payload["planned_employee_count"], 1)
        self.assertEqual(payload["preference_summary"]["ready_count"], 1)
        self.assertEqual(payload["analytics_chart_payload"]["sources"]["schedule"][2], 8)
