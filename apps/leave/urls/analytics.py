from django.urls import path

from apps.leave.views import analytics


urlpatterns = [
    path("analytics/", analytics.analytics, name="analytics"),
]
