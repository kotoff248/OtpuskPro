from apps.leave.urls.analytics import urlpatterns as analytics_urlpatterns
from apps.leave.urls.applications import urlpatterns as applications_urlpatterns
from apps.leave.urls.calendar import urlpatterns as calendar_urlpatterns
from apps.leave.urls.preferences import urlpatterns as preferences_urlpatterns
from apps.leave.urls.schedule import urlpatterns as schedule_urlpatterns


urlpatterns = [
    *calendar_urlpatterns,
    *schedule_urlpatterns,
    *preferences_urlpatterns,
    *applications_urlpatterns,
    *analytics_urlpatterns,
]
