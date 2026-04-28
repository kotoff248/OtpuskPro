from datetime import date

from django.urls import reverse

from apps.leave.models import VacationRequest
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
