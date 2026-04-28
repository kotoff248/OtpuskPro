from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string

from apps.accounts.services import employee_required, get_current_employee, get_user_context
from apps.core.models import Notification
from apps.core.services.notifications import (
    delete_notification,
    get_notification_filter_counts,
    get_notifications_for_employee,
    mark_notification_done,
    mark_notification_read,
    normalize_notification_filter,
)
from apps.employees.services import update_context_with_departments


@employee_required
def notifications(request):
    current_employee = get_current_employee(request)
    selected_filter = normalize_notification_filter(request.GET.get("filter"))

    if request.method == "POST":
        notification = get_object_or_404(Notification, pk=request.POST.get("notification_id"), recipient=current_employee)
        action = request.POST.get("action")
        if action == "delete":
            delete_notification(notification, employee=current_employee)
            messages.success(request, "Уведомление удалено.")
        elif action == "mark_done":
            mark_notification_done(notification, employee=current_employee)
            messages.success(request, "Уведомление завершено.")
        else:
            mark_notification_read(notification, employee=current_employee)
            messages.success(request, "Уведомление отмечено как прочитанное.")
        return redirect(f"{request.path}?filter={selected_filter}")

    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    context.update(
        {
            "notifications": get_notifications_for_employee(current_employee, selected_filter),
            "notification_filter": selected_filter,
            "notification_counts": get_notification_filter_counts(current_employee),
        }
    )
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse(
            {
                "notifications_html": render_to_string(
                    "includes/notifications/list.html",
                    context,
                    request=request,
                ),
                "counts": context["notification_counts"],
                "filter": selected_filter,
            }
        )
    return render(request, "notifications.html", context)
