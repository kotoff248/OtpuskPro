from datetime import date

from django.urls import reverse

from apps.core.models import Notification
from apps.leave.models import VacationRequest, VacationSchedule, VacationScheduleItem
from apps.leave.services.requests import approve_vacation_request, create_vacation_request
from apps.leave.services.schedule_changes import approve_schedule_change_request, create_schedule_change_request
from apps.leave.tests.base import LeaveTestCase


class NotificationWorkflowTests(LeaveTestCase):
    def test_vacation_request_notifies_only_expected_approver(self):
        request_obj = create_vacation_request(
            employee=self.employee,
            start_date=date(2027, 2, 2),
            end_date=date(2027, 2, 4),
            vacation_type="unpaid",
            reason="Семейные обстоятельства.",
        )

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.department_head,
                actor=self.employee,
                event_type=Notification.TYPE_VACATION_REQUEST_CREATED,
                requires_action=True,
                action_url=reverse("vacation_detail", args=[request_obj.id]),
            ).exists()
        )
        self.assertFalse(Notification.objects.filter(recipient=self.hr_employee).exists())
        self.assertFalse(Notification.objects.filter(recipient=self.enterprise_head).exists())

    def test_management_requests_follow_approval_chain(self):
        department_head_request = create_vacation_request(
            employee=self.department_head,
            start_date=date(2027, 3, 2),
            end_date=date(2027, 3, 4),
            vacation_type="unpaid",
            reason="Личные обстоятельства.",
        )
        enterprise_head_request = create_vacation_request(
            employee=self.enterprise_head,
            start_date=date(2027, 4, 2),
            end_date=date(2027, 4, 4),
            vacation_type="unpaid",
            reason="Личные обстоятельства.",
        )

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.enterprise_head,
                event_type=Notification.TYPE_VACATION_REQUEST_CREATED,
                dedupe_key=f"{Notification.TYPE_VACATION_REQUEST_CREATED}:{department_head_request.id}:{self.enterprise_head.id}",
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.authorized_person,
                event_type=Notification.TYPE_VACATION_REQUEST_CREATED,
                dedupe_key=f"{Notification.TYPE_VACATION_REQUEST_CREATED}:{enterprise_head_request.id}:{self.authorized_person.id}",
            ).exists()
        )

    def test_vacation_review_completes_approver_task_and_notifies_employee(self):
        request_obj = create_vacation_request(
            employee=self.employee,
            start_date=date(2027, 5, 2),
            end_date=date(2027, 5, 4),
            vacation_type="unpaid",
            reason="Семейные обстоятельства.",
        )
        approve_vacation_request(request_obj.id, reviewer=self.department_head)

        approver_task = Notification.objects.get(
            dedupe_key=f"{Notification.TYPE_VACATION_REQUEST_CREATED}:{request_obj.id}:{self.department_head.id}"
        )
        employee_notice = Notification.objects.get(
            recipient=self.employee,
            event_type=Notification.TYPE_VACATION_REQUEST_APPROVED,
        )

        self.assertEqual(approver_task.status, Notification.STATUS_DONE)
        self.assertFalse(employee_notice.requires_action)
        self.assertIn("одобрена", employee_notice.message)

    def test_schedule_change_notifications_follow_same_workflow(self):
        schedule = VacationSchedule.objects.create(
            year=2027,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        schedule_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2027, 7, 1),
            end_date=date(2027, 7, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
        )

        change_request = create_schedule_change_request(
            schedule_item.id,
            requested_by=self.employee,
            new_start_date=date(2027, 8, 1),
            new_end_date=date(2027, 8, 14),
            reason="Нужно перенести.",
        )
        approve_schedule_change_request(change_request.id, reviewer=self.department_head)

        approver_task = Notification.objects.get(
            dedupe_key=f"{Notification.TYPE_SCHEDULE_CHANGE_CREATED}:{change_request.id}:{self.department_head.id}"
        )
        employee_notice = Notification.objects.get(
            recipient=self.employee,
            event_type=Notification.TYPE_SCHEDULE_CHANGE_APPROVED,
        )

        self.assertEqual(approver_task.status, Notification.STATUS_DONE)
        self.assertIn(reverse("calendar"), employee_notice.action_url)


class NotificationPageTests(LeaveTestCase):
    def test_notifications_page_shows_items_and_sidebar_counter(self):
        Notification.objects.create(
            recipient=self.department_head,
            actor=self.employee,
            event_type=Notification.TYPE_VACATION_REQUEST_CREATED,
            title="Новая заявка на отпуск",
            message="Сотрудник отправил заявку.",
            action_url=reverse("applications"),
            requires_action=True,
        )
        self.client.force_login(self.department_head.user)

        response = self.client.get(reverse("notifications"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Новая заявка на отпуск")
        self.assertEqual(response.context["unread_notifications_count"], 1)
        self.assertEqual(response.context["notification_counts"]["action"], 1)

    def test_notifications_filter_ajax_returns_partial_html_and_counts(self):
        Notification.objects.create(
            recipient=self.department_head,
            actor=self.employee,
            event_type=Notification.TYPE_VACATION_REQUEST_CREATED,
            title="Новая заявка на отпуск",
            message="Сотрудник отправил заявку.",
            requires_action=True,
        )
        Notification.objects.create(
            recipient=self.department_head,
            actor=self.employee,
            event_type=Notification.TYPE_VACATION_REQUEST_APPROVED,
            title="Заявка завершена",
            message="Сотруднику отправлен результат.",
            status=Notification.STATUS_DONE,
        )
        self.client.force_login(self.department_head.user)

        response = self.client.get(
            f'{reverse("notifications")}?filter=done',
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["counts"]["all"], 2)
        self.assertEqual(payload["counts"]["new"], 1)
        self.assertEqual(payload["counts"]["action"], 1)
        self.assertEqual(payload["counts"]["done"], 1)
        self.assertIn("Заявка завершена", payload["notifications_html"])
        self.assertNotIn("Новая заявка на отпуск", payload["notifications_html"])

    def test_user_can_mark_notification_read_from_page(self):
        notification = Notification.objects.create(
            recipient=self.department_head,
            actor=self.employee,
            event_type=Notification.TYPE_VACATION_REQUEST_CREATED,
            title="Новая заявка на отпуск",
            message="Сотрудник отправил заявку.",
        )
        self.client.force_login(self.department_head.user)

        response = self.client.post(
            f'{reverse("notifications")}?filter=new',
            {"notification_id": notification.id, "action": "mark_read"},
        )
        notification.refresh_from_db()

        self.assertRedirects(response, f'{reverse("notifications")}?filter=new')
        self.assertEqual(notification.status, Notification.STATUS_READ)

    def test_user_cannot_mark_another_employee_notification(self):
        notification = Notification.objects.create(
            recipient=self.department_head,
            actor=self.employee,
            event_type=Notification.TYPE_VACATION_REQUEST_CREATED,
            title="Новая заявка на отпуск",
            message="Сотрудник отправил заявку.",
        )
        self.client.force_login(self.enterprise_head.user)

        response = self.client.post(
            reverse("notifications"),
            {"notification_id": notification.id, "action": "mark_read"},
        )
        notification.refresh_from_db()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(notification.status, Notification.STATUS_NEW)
