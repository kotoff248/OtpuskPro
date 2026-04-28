from django.contrib import admin

from apps.core.models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "recipient", "event_type", "status", "requires_action", "created_at")
    list_filter = ("status", "event_type", "requires_action", "priority")
    search_fields = ("title", "message", "recipient__last_name", "recipient__login", "dedupe_key")
    readonly_fields = ("created_at", "updated_at", "read_at", "done_at")
