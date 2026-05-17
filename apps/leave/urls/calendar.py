from django.urls import path

from apps.leave.views import calendar


urlpatterns = [
    path("calendar/", calendar.graphics, name="calendar"),
    path("calendar/date-picker-periods/", calendar.calendar_date_picker_periods, name="calendar_date_picker_periods"),
    path("calendar/vacation-request-preview/", calendar.vacation_request_preview, name="vacation_request_preview"),
    path(
        "calendar/schedule-items/<int:item_id>/transfer-preview/",
        calendar.schedule_change_preview,
        name="schedule_change_request_preview",
    ),
]
