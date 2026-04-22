from django.urls import path

from . import views


urlpatterns = [
    path("calendar/", views.graphics, name="calendar"),
    path("applications/", views.applications, name="applications"),
    path("applications/<int:pk>/", views.vacation_detail, name="vacation_detail"),
    path("applications/<int:pk>/approve/", views.approve_vacation, name="approve_vacation"),
    path("applications/<int:pk>/reject/", views.reject_vacation, name="reject_vacation"),
    path("applications/<int:pk>/delete/", views.delete_vacation, name="delete_vacation"),
    path("analytics/", views.analytics, name="analytics"),
]


