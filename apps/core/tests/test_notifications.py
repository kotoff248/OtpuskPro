from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone

from apps.core.models import Notification
from apps.leave.models import (
    VacationRequest,
    VacationSchedule,
    VacationScheduleChangeRequest,
    VacationScheduleItem,
)
from apps.leave.services.notifications import (
    backfill_pending_approval_notifications,
    notify_schedule_item_changed_by_manager,
    send_upcoming_vacation_reminders,
)
from apps.leave.services.requests import approve_vacation_request, create_vacation_request, delete_pending_vacation_request
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

    def test_deleting_pending_vacation_request_removes_related_notifications(self):
        request_obj = create_vacation_request(
            employee=self.employee,
            start_date=date(2027, 6, 2),
            end_date=date(2027, 6, 4),
            vacation_type="unpaid",
            reason="Личные обстоятельства.",
        )
        detail_url = reverse("vacation_detail", args=[request_obj.id])

        self.assertTrue(Notification.objects.filter(action_url=detail_url).exists())

        delete_pending_vacation_request(request_obj.id, actor=self.employee)

        self.assertFalse(Notification.objects.filter(action_url=detail_url).exists())

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
        self.assertEqual(approver_task.action_url, reverse("schedule_change_detail", args=[change_request.id]))
        self.assertEqual(employee_notice.action_url, reverse("schedule_change_detail", args=[change_request.id]))
        self.assertFalse(
            Notification.objects.filter(
                recipient=self.employee,
                event_type=Notification.TYPE_SCHEDULE_ITEM_CHANGED_BY_MANAGER,
            ).exists()
        )

    def test_manager_initiated_schedule_change_notifications_go_to_employee_then_initiator(self):
        schedule = VacationSchedule.objects.create(
            year=2027,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        schedule_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2027, 9, 1),
            end_date=date(2027, 9, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
        )

        change_request = create_schedule_change_request(
            schedule_item.id,
            requested_by=self.department_head,
            new_start_date=date(2027, 10, 1),
            new_end_date=date(2027, 10, 14),
            reason="Предложение руководителя.",
        )

        employee_task = Notification.objects.get(
            dedupe_key=f"{Notification.TYPE_SCHEDULE_CHANGE_CREATED}:{change_request.id}:{self.employee.id}"
        )
        self.assertEqual(employee_task.recipient_id, self.employee.id)
        self.assertEqual(employee_task.actor_id, self.department_head.id)
        self.assertIn("предложил", employee_task.message)
        self.assertFalse(
            Notification.objects.filter(
                dedupe_key=f"{Notification.TYPE_SCHEDULE_CHANGE_CREATED}:{change_request.id}:{self.department_head.id}"
            ).exists()
        )

        approve_schedule_change_request(change_request.id, reviewer=self.employee)

        employee_task.refresh_from_db()
        initiator_notice = Notification.objects.get(
            recipient=self.department_head,
            event_type=Notification.TYPE_SCHEDULE_CHANGE_APPROVED,
        )
        self.assertEqual(employee_task.status, Notification.STATUS_DONE)
        self.assertEqual(initiator_notice.actor_id, self.employee.id)
        self.assertIn("предложение переноса", initiator_notice.message)

    def test_backfill_creates_missing_pending_approval_notifications(self):
        request_obj = VacationRequest.objects.create(
            employee=self.employee,
            start_date=date(2027, 9, 2),
            end_date=date(2027, 9, 4),
            vacation_type="unpaid",
            status=VacationRequest.STATUS_PENDING,
            reason="Создано до внедрения уведомлений.",
        )
        schedule = VacationSchedule.objects.create(
            year=2027,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        schedule_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2027, 10, 1),
            end_date=date(2027, 10, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        change_request = VacationScheduleChangeRequest.objects.create(
            schedule_item=schedule_item,
            employee=self.employee,
            old_start_date=schedule_item.start_date,
            old_end_date=schedule_item.end_date,
            new_start_date=date(2027, 11, 1),
            new_end_date=date(2027, 11, 14),
            requested_by=self.employee,
            reason="Создано до внедрения уведомлений.",
            status=VacationScheduleChangeRequest.STATUS_PENDING,
        )

        stats = backfill_pending_approval_notifications()
        repeat_stats = backfill_pending_approval_notifications()

        self.assertEqual(stats["vacation_requests"], 1)
        self.assertEqual(stats["schedule_changes"], 1)
        self.assertEqual(stats["notifications_created"], 2)
        self.assertEqual(repeat_stats["notifications_created"], 0)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.department_head,
                dedupe_key=f"{Notification.TYPE_VACATION_REQUEST_CREATED}:{request_obj.id}:{self.department_head.id}",
                requires_action=True,
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.department_head,
                dedupe_key=f"{Notification.TYPE_SCHEDULE_CHANGE_CREATED}:{change_request.id}:{self.department_head.id}",
                requires_action=True,
                action_url=reverse("schedule_change_detail", args=[change_request.id]),
            ).exists()
        )

    def test_backfill_retargets_stale_schedule_change_notification_to_detail_page(self):
        schedule = VacationSchedule.objects.create(
            year=2027,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        schedule_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2027, 10, 1),
            end_date=date(2027, 10, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        change_request = VacationScheduleChangeRequest.objects.create(
            schedule_item=schedule_item,
            employee=self.employee,
            old_start_date=schedule_item.start_date,
            old_end_date=schedule_item.end_date,
            new_start_date=date(2027, 11, 1),
            new_end_date=date(2027, 11, 14),
            requested_by=self.employee,
            reason="Создано до страницы деталей переноса.",
            status=VacationScheduleChangeRequest.STATUS_PENDING,
        )
        stale_task = Notification.objects.create(
            recipient=self.department_head,
            actor=self.employee,
            event_type=Notification.TYPE_SCHEDULE_CHANGE_CREATED,
            title="Новый запрос переноса отпуска",
            message="Старая ссылка открывала общий список.",
            action_url=f'{reverse("applications")}?status=pending&search={self.employee.full_name}',
            priority=Notification.PRIORITY_HIGH,
            requires_action=True,
            dedupe_key=f"{Notification.TYPE_SCHEDULE_CHANGE_CREATED}:{change_request.id}:{self.department_head.id}",
        )

        stats = backfill_pending_approval_notifications()
        stale_task.refresh_from_db()

        self.assertGreaterEqual(stats["notifications_updated"], 1)
        self.assertEqual(stale_task.action_url, reverse("schedule_change_detail", args=[change_request.id]))

    def test_backfill_manager_initiated_pending_schedule_change_targets_employee(self):
        schedule = VacationSchedule.objects.create(
            year=2028,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        schedule_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2028, 1, 1),
            end_date=date(2028, 1, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        change_request = VacationScheduleChangeRequest.objects.create(
            schedule_item=schedule_item,
            employee=self.employee,
            old_start_date=schedule_item.start_date,
            old_end_date=schedule_item.end_date,
            new_start_date=date(2028, 2, 1),
            new_end_date=date(2028, 2, 14),
            requested_by=self.department_head,
            status=VacationScheduleChangeRequest.STATUS_PENDING,
            reason="Предложение руководителя.",
        )

        stats = backfill_pending_approval_notifications()

        self.assertGreaterEqual(stats["notifications_created"], 1)
        employee_task = Notification.objects.get(
            dedupe_key=f"{Notification.TYPE_SCHEDULE_CHANGE_CREATED}:{change_request.id}:{self.employee.id}"
        )
        self.assertEqual(employee_task.recipient_id, self.employee.id)
        self.assertEqual(employee_task.actor_id, self.department_head.id)
        self.assertTrue(employee_task.requires_action)
        self.assertFalse(
            Notification.objects.filter(
                dedupe_key=f"{Notification.TYPE_SCHEDULE_CHANGE_CREATED}:{change_request.id}:{self.department_head.id}",
            ).exists()
        )

    def test_backfill_completes_reviewed_request_task_and_marks_result_read(self):
        reviewed_at = timezone.now() - timedelta(days=2)
        request_obj = VacationRequest.objects.create(
            employee=self.employee,
            start_date=date(2028, 1, 10),
            end_date=date(2028, 1, 12),
            vacation_type="unpaid",
            status=VacationRequest.STATUS_APPROVED,
            reviewed_by=self.department_head,
            reviewed_at=reviewed_at,
            reason="Историческая заявка.",
        )
        stale_task = Notification.objects.create(
            recipient=self.department_head,
            actor=self.employee,
            event_type=Notification.TYPE_VACATION_REQUEST_CREATED,
            title="Новая заявка на отпуск",
            message="Сотрудник отправил заявку.",
            action_url=reverse("vacation_detail", args=[request_obj.id]),
            requires_action=True,
            dedupe_key=f"{Notification.TYPE_VACATION_REQUEST_CREATED}:{request_obj.id}:{self.department_head.id}",
        )

        stats = backfill_pending_approval_notifications()
        repeat_stats = backfill_pending_approval_notifications()
        stale_task.refresh_from_db()
        employee_notice = Notification.objects.get(
            recipient=self.employee,
            event_type=Notification.TYPE_VACATION_REQUEST_APPROVED,
        )

        self.assertEqual(stale_task.status, Notification.STATUS_DONE)
        self.assertEqual(employee_notice.status, Notification.STATUS_READ)
        self.assertEqual(stats["notifications_created"], 1)
        self.assertGreaterEqual(stats["notifications_updated"], 1)
        self.assertEqual(repeat_stats["notifications_created"], 0)
        self.assertEqual(repeat_stats["notifications_updated"], 0)

    def test_backfill_completes_reviewed_schedule_change_and_marks_result_read(self):
        reviewed_at = timezone.now() - timedelta(days=3)
        schedule = VacationSchedule.objects.create(
            year=2028,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        schedule_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2028, 2, 1),
            end_date=date(2028, 2, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        change_request = VacationScheduleChangeRequest.objects.create(
            schedule_item=schedule_item,
            employee=self.employee,
            old_start_date=schedule_item.start_date,
            old_end_date=schedule_item.end_date,
            new_start_date=date(2028, 3, 1),
            new_end_date=date(2028, 3, 14),
            requested_by=self.employee,
            reviewed_by=self.department_head,
            reviewed_at=reviewed_at,
            status=VacationScheduleChangeRequest.STATUS_REJECTED,
            reason="Исторический перенос.",
        )

        stats = backfill_pending_approval_notifications()
        approver_task = Notification.objects.get(
            dedupe_key=f"{Notification.TYPE_SCHEDULE_CHANGE_CREATED}:{change_request.id}:{self.department_head.id}"
        )
        employee_notice = Notification.objects.get(
            recipient=self.employee,
            event_type=Notification.TYPE_SCHEDULE_CHANGE_REJECTED,
        )

        self.assertEqual(approver_task.status, Notification.STATUS_DONE)
        self.assertEqual(employee_notice.status, Notification.STATUS_READ)
        self.assertEqual(approver_task.action_url, reverse("schedule_change_detail", args=[change_request.id]))
        self.assertEqual(employee_notice.action_url, reverse("schedule_change_detail", args=[change_request.id]))
        self.assertGreaterEqual(stats["notifications_created"], 2)

    def test_backfill_completes_reviewed_manager_initiated_schedule_change_for_initiator(self):
        reviewed_at = timezone.now() - timedelta(days=3)
        schedule = VacationSchedule.objects.create(
            year=2028,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        schedule_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2028, 4, 1),
            end_date=date(2028, 4, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        change_request = VacationScheduleChangeRequest.objects.create(
            schedule_item=schedule_item,
            employee=self.employee,
            old_start_date=schedule_item.start_date,
            old_end_date=schedule_item.end_date,
            new_start_date=date(2028, 5, 1),
            new_end_date=date(2028, 5, 14),
            requested_by=self.department_head,
            reviewed_by=self.employee,
            reviewed_at=reviewed_at,
            status=VacationScheduleChangeRequest.STATUS_REJECTED,
            reason="Предложение руководителя.",
        )

        stats = backfill_pending_approval_notifications()
        employee_task = Notification.objects.get(
            dedupe_key=f"{Notification.TYPE_SCHEDULE_CHANGE_CREATED}:{change_request.id}:{self.employee.id}"
        )
        initiator_notice = Notification.objects.get(
            recipient=self.department_head,
            event_type=Notification.TYPE_SCHEDULE_CHANGE_REJECTED,
        )

        self.assertEqual(employee_task.status, Notification.STATUS_DONE)
        self.assertEqual(initiator_notice.actor_id, self.employee.id)
        self.assertEqual(initiator_notice.action_url, reverse("schedule_change_detail", args=[change_request.id]))
        self.assertFalse(initiator_notice.requires_action)
        self.assertGreaterEqual(stats["notifications_created"], 2)

    def test_manager_changed_schedule_item_notifies_employee_without_transfer_duplicates(self):
        schedule = VacationSchedule.objects.create(
            year=2028,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        manual_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2028, 4, 1),
            end_date=date(2028, 4, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
            source=VacationScheduleItem.SOURCE_MANUAL,
            was_changed_by_manager=True,
        )
        transfer_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2028, 5, 1),
            end_date=date(2028, 5, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
            source=VacationScheduleItem.SOURCE_TRANSFER,
            was_changed_by_manager=True,
        )

        notification = notify_schedule_item_changed_by_manager(manual_item, actor=self.department_head)
        skipped_notification = notify_schedule_item_changed_by_manager(transfer_item, actor=self.department_head)

        self.assertIsNotNone(notification)
        self.assertIsNone(skipped_notification)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.employee,
                actor=self.department_head,
                event_type=Notification.TYPE_SCHEDULE_ITEM_CHANGED_BY_MANAGER,
                action_url__contains="view=month",
            ).exists()
        )

    def test_rejected_transfer_source_item_does_not_create_manager_changed_notice(self):
        schedule = VacationSchedule.objects.create(
            year=2028,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        source_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2028, 6, 1),
            end_date=date(2028, 6, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
            source=VacationScheduleItem.SOURCE_GENERATED,
            was_changed_by_manager=True,
        )
        VacationScheduleChangeRequest.objects.create(
            schedule_item=source_item,
            employee=self.employee,
            old_start_date=source_item.start_date,
            old_end_date=source_item.end_date,
            new_start_date=date(2028, 8, 1),
            new_end_date=date(2028, 8, 14),
            reason="Производственная необходимость.",
            status=VacationScheduleChangeRequest.STATUS_REJECTED,
            requested_by=self.employee,
            reviewed_by=self.department_head,
            review_comment="Период признан рискованным.",
            reviewed_at=timezone.now(),
        )
        stale_notification = Notification.objects.create(
            recipient=self.employee,
            event_type=Notification.TYPE_SCHEDULE_ITEM_CHANGED_BY_MANAGER,
            title="График отпуска изменён",
            message="Руководитель изменил(а) период вашего отпуска: 01.06.2028 - 14.06.2028.",
            action_url="/calendar/?view=month&year=2028&month=6",
            dedupe_key=f"{Notification.TYPE_SCHEDULE_ITEM_CHANGED_BY_MANAGER}:{source_item.id}:{self.employee.id}",
        )

        self.assertIsNone(notify_schedule_item_changed_by_manager(source_item, actor=self.department_head))

        backfill_pending_approval_notifications()

        self.assertFalse(Notification.objects.filter(id=stale_notification.id).exists())
        self.assertFalse(
            Notification.objects.filter(
                recipient=self.employee,
                event_type=Notification.TYPE_SCHEDULE_ITEM_CHANGED_BY_MANAGER,
                dedupe_key=f"{Notification.TYPE_SCHEDULE_ITEM_CHANGED_BY_MANAGER}:{source_item.id}:{self.employee.id}",
            ).exists()
        )

    def test_upcoming_vacation_reminder_created_for_schedule_item(self):
        as_of_date = self.today
        start_date = as_of_date + timedelta(days=7)
        schedule = VacationSchedule.objects.create(
            year=start_date.year,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        schedule_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=start_date,
            end_date=start_date + timedelta(days=13),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
        )

        stats = send_upcoming_vacation_reminders(as_of_date=as_of_date)
        repeat_stats = send_upcoming_vacation_reminders(as_of_date=as_of_date)

        self.assertEqual(stats["notifications_created"], 1)
        self.assertEqual(repeat_stats["notifications_created"], 0)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.employee,
                event_type=Notification.TYPE_UPCOMING_VACATION_REMINDER,
                dedupe_key__contains=f"schedule_item:{schedule_item.id}",
                status=Notification.STATUS_NEW,
            ).exists()
        )

    def test_converted_paid_request_has_single_upcoming_reminder(self):
        as_of_date = self.today
        start_date = as_of_date + timedelta(days=7)
        schedule = VacationSchedule.objects.create(
            year=start_date.year,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        request_obj = VacationRequest.objects.create(
            employee=self.employee,
            start_date=start_date,
            end_date=start_date + timedelta(days=6),
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
            reviewed_by=self.department_head,
            reviewed_at=timezone.now(),
        )
        schedule_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=request_obj.start_date,
            end_date=request_obj.end_date,
            vacation_type="paid",
            chargeable_days=7,
            status=VacationScheduleItem.STATUS_APPROVED,
            source=VacationScheduleItem.SOURCE_MANUAL,
            created_from_vacation_request=request_obj,
        )

        stats = send_upcoming_vacation_reminders(as_of_date=as_of_date)

        self.assertEqual(stats["notifications_created"], 1)
        self.assertEqual(
            Notification.objects.filter(
                recipient=self.employee,
                event_type=Notification.TYPE_UPCOMING_VACATION_REMINDER,
            ).count(),
            1,
        )
        self.assertTrue(
            Notification.objects.filter(
                dedupe_key__contains=f"schedule_item:{schedule_item.id}",
            ).exists()
        )


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

    def test_user_can_toggle_notification_read_state_with_ajax(self):
        notification = Notification.objects.create(
            recipient=self.department_head,
            actor=self.employee,
            event_type=Notification.TYPE_VACATION_REQUEST_CREATED,
            title="Новая заявка на отпуск",
            message="Сотрудник отправил заявку.",
        )
        self.client.force_login(self.department_head.user)

        read_response = self.client.post(
            f'{reverse("notifications")}?filter=all',
            {"notification_id": notification.id, "action": "mark_read"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        notification.refresh_from_db()

        self.assertEqual(read_response.status_code, 200)
        self.assertEqual(notification.status, Notification.STATUS_READ)
        self.assertEqual(read_response.json()["counts"]["new"], 0)
        self.assertIn("mark_unread", read_response.json()["notifications_html"])

        unread_response = self.client.post(
            f'{reverse("notifications")}?filter=all',
            {"notification_id": notification.id, "action": "mark_unread"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        notification.refresh_from_db()

        self.assertEqual(unread_response.status_code, 200)
        self.assertEqual(notification.status, Notification.STATUS_NEW)
        self.assertEqual(unread_response.json()["counts"]["new"], 1)

    def test_user_can_toggle_notification_done_state_with_ajax(self):
        notification = Notification.objects.create(
            recipient=self.department_head,
            actor=self.employee,
            event_type=Notification.TYPE_SCHEDULE_REVIEW_REQUESTED,
            title="График ожидает проверки",
            message="Проверьте график отпусков.",
            requires_action=True,
        )
        self.client.force_login(self.department_head.user)

        done_response = self.client.post(
            f'{reverse("notifications")}?filter=all',
            {"notification_id": notification.id, "action": "mark_done"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        notification.refresh_from_db()

        self.assertEqual(done_response.status_code, 200)
        self.assertEqual(notification.status, Notification.STATUS_DONE)
        self.assertEqual(done_response.json()["counts"]["done"], 1)
        self.assertIn("mark_active", done_response.json()["notifications_html"])

        active_response = self.client.post(
            f'{reverse("notifications")}?filter=all',
            {"notification_id": notification.id, "action": "mark_active"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        notification.refresh_from_db()

        self.assertEqual(active_response.status_code, 200)
        self.assertEqual(notification.status, Notification.STATUS_READ)
        self.assertEqual(active_response.json()["counts"]["action"], 1)
        self.assertEqual(active_response.json()["counts"]["done"], 0)

    def test_managed_approval_task_cannot_be_manually_marked_done(self):
        notification = Notification.objects.create(
            recipient=self.department_head,
            actor=self.employee,
            event_type=Notification.TYPE_VACATION_REQUEST_CREATED,
            title="Новая заявка на отпуск",
            message="Сотрудник отправил заявку.",
            requires_action=True,
        )
        self.client.force_login(self.department_head.user)

        page_response = self.client.get(reverse("notifications"))
        done_response = self.client.post(
            f'{reverse("notifications")}?filter=all',
            {"notification_id": notification.id, "action": "mark_done"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        notification.refresh_from_db()

        self.assertNotContains(page_response, "mark_done")
        self.assertEqual(done_response.status_code, 200)
        self.assertEqual(notification.status, Notification.STATUS_NEW)
        self.assertEqual(done_response.json()["counts"]["action"], 1)
        self.assertEqual(done_response.json()["counts"]["done"], 0)

    def test_user_can_delete_own_notification_from_page(self):
        notification = Notification.objects.create(
            recipient=self.department_head,
            actor=self.employee,
            event_type=Notification.TYPE_VACATION_REQUEST_CREATED,
            title="Новая заявка на отпуск",
            message="Сотрудник отправил заявку.",
            requires_action=True,
        )
        self.client.force_login(self.department_head.user)

        page_response = self.client.get(reverse("notifications"))
        delete_response = self.client.post(
            f'{reverse("notifications")}?filter=all',
            {"notification_id": notification.id, "action": "delete"},
        )

        self.assertContains(page_response, "data-notification-delete-open")
        self.assertContains(page_response, "notification-delete-modal")
        self.assertRedirects(delete_response, f'{reverse("notifications")}?filter=all')
        self.assertFalse(Notification.objects.filter(id=notification.id).exists())

    def test_user_can_delete_notification_with_ajax(self):
        notification = Notification.objects.create(
            recipient=self.department_head,
            actor=self.employee,
            event_type=Notification.TYPE_VACATION_REQUEST_CREATED,
            title="Старая заявка на отпуск",
            message="Сотрудник отправил заявку.",
            requires_action=True,
        )
        self.client.force_login(self.department_head.user)

        response = self.client.post(
            f'{reverse("notifications")}?filter=all',
            {"notification_id": notification.id, "action": "delete"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Notification.objects.filter(id=notification.id).exists())
        self.assertEqual(response.json()["counts"]["all"], 0)
        self.assertIn("Уведомлений нет", response.json()["notifications_html"])

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

    def test_user_cannot_delete_another_employee_notification(self):
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
            {"notification_id": notification.id, "action": "delete"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Notification.objects.filter(id=notification.id).exists())
