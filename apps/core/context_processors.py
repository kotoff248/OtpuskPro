from apps.accounts.services import get_current_employee
from apps.core.services.notifications import get_unread_notifications_count


def unread_notifications_count(request):
    return {
        "unread_notifications_count": get_unread_notifications_count(get_current_employee(request)),
    }
