from django.utils import timezone

from apps.core.models import Notification


NOTIFICATION_FILTER_ALL = "all"
NOTIFICATION_FILTER_NEW = "new"
NOTIFICATION_FILTER_ACTION = "action"
NOTIFICATION_FILTER_DONE = "done"
NOTIFICATION_FILTERS = {
    NOTIFICATION_FILTER_ALL,
    NOTIFICATION_FILTER_NEW,
    NOTIFICATION_FILTER_ACTION,
    NOTIFICATION_FILTER_DONE,
}


def normalize_notification_filter(value):
    return value if value in NOTIFICATION_FILTERS else NOTIFICATION_FILTER_ALL


def create_notification(
    *,
    recipient,
    event_type,
    title,
    message,
    actor=None,
    action_url="",
    priority=Notification.PRIORITY_NORMAL,
    requires_action=False,
    dedupe_key=None,
    status=Notification.STATUS_NEW,
    created_at=None,
    read_at=None,
    done_at=None,
):
    if recipient is None:
        return None

    payload = {
        "recipient": recipient,
        "actor": actor,
        "event_type": event_type,
        "title": title,
        "message": message,
        "action_url": action_url or "",
        "priority": priority,
        "requires_action": requires_action,
        "status": status,
        "read_at": read_at,
        "done_at": done_at,
    }

    if dedupe_key:
        notification, _ = Notification.objects.get_or_create(
            dedupe_key=dedupe_key,
            defaults=payload,
        )
        if created_at is not None and notification.created_at != created_at:
            Notification.objects.filter(pk=notification.pk).update(created_at=created_at)
            notification.created_at = created_at
        return notification

    notification = Notification.objects.create(**payload)
    if created_at is not None:
        Notification.objects.filter(pk=notification.pk).update(created_at=created_at)
        notification.created_at = created_at
    return notification


def is_managed_action_notification(notification):
    return notification.is_managed_action_task


def get_notifications_for_employee(employee, selected_filter=NOTIFICATION_FILTER_ALL):
    selected_filter = normalize_notification_filter(selected_filter)
    queryset = Notification.objects.select_related("actor", "recipient").filter(recipient=employee)

    if selected_filter == NOTIFICATION_FILTER_NEW:
        queryset = queryset.filter(status=Notification.STATUS_NEW)
    elif selected_filter == NOTIFICATION_FILTER_ACTION:
        queryset = queryset.filter(requires_action=True).exclude(status=Notification.STATUS_DONE)
    elif selected_filter == NOTIFICATION_FILTER_DONE:
        queryset = queryset.filter(status=Notification.STATUS_DONE)

    return queryset


def get_unread_notifications_count(employee):
    if employee is None:
        return 0
    return Notification.objects.filter(recipient=employee, status=Notification.STATUS_NEW).count()


def get_notification_filter_counts(employee):
    if employee is None:
        return {
            NOTIFICATION_FILTER_ALL: 0,
            NOTIFICATION_FILTER_NEW: 0,
            NOTIFICATION_FILTER_ACTION: 0,
            NOTIFICATION_FILTER_DONE: 0,
        }

    queryset = Notification.objects.filter(recipient=employee)
    return {
        NOTIFICATION_FILTER_ALL: queryset.count(),
        NOTIFICATION_FILTER_NEW: queryset.filter(status=Notification.STATUS_NEW).count(),
        NOTIFICATION_FILTER_ACTION: queryset.filter(requires_action=True)
        .exclude(status=Notification.STATUS_DONE)
        .count(),
        NOTIFICATION_FILTER_DONE: queryset.filter(status=Notification.STATUS_DONE).count(),
    }


def mark_notification_read(notification, *, employee):
    if notification.recipient_id != employee.id:
        return notification
    if notification.status == Notification.STATUS_NEW:
        notification.status = Notification.STATUS_READ
        notification.read_at = timezone.now()
        notification.save(update_fields=["status", "read_at", "updated_at"])
    return notification


def mark_notification_unread(notification, *, employee):
    if notification.recipient_id != employee.id:
        return notification
    if is_managed_action_notification(notification) and notification.status == Notification.STATUS_DONE:
        return notification
    if notification.status != Notification.STATUS_NEW:
        notification.status = Notification.STATUS_NEW
        notification.read_at = None
        notification.done_at = None
        notification.save(update_fields=["status", "read_at", "done_at", "updated_at"])
    return notification


def mark_notification_done(notification, *, employee):
    if notification.recipient_id != employee.id:
        return notification
    if is_managed_action_notification(notification):
        return notification
    if notification.status != Notification.STATUS_DONE:
        now = timezone.now()
        notification.status = Notification.STATUS_DONE
        notification.done_at = now
        if notification.read_at is None:
            notification.read_at = now
        notification.save(update_fields=["status", "read_at", "done_at", "updated_at"])
    return notification


def mark_notification_active(notification, *, employee):
    if notification.recipient_id != employee.id:
        return notification
    if is_managed_action_notification(notification):
        return notification
    if notification.status == Notification.STATUS_DONE:
        notification.status = Notification.STATUS_READ
        notification.done_at = None
        if notification.read_at is None:
            notification.read_at = timezone.now()
        notification.save(update_fields=["status", "read_at", "done_at", "updated_at"])
    return notification


def delete_notification(notification, *, employee):
    if notification.recipient_id != employee.id:
        return False
    notification.delete()
    return True


def mark_notifications_done_by_dedupe_prefix(dedupe_prefix):
    now = timezone.now()
    return (
        Notification.objects.filter(dedupe_key__startswith=dedupe_prefix)
        .exclude(status=Notification.STATUS_DONE)
        .update(status=Notification.STATUS_DONE, read_at=now, done_at=now, updated_at=now)
    )
