from django.contrib import admin
from django.urls import path

from main import views


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("main/", views.main, name="main"),
    path("calendar/", views.graphics, name="calendar"),
    path("employees/", views.employees, name="employees"),
    path("employee/<int:employee_id>/", views.employee_profile, name="employee_profile"),
    path("employee/<int:employee_id>/update/", views.update_employee, name="update_employee"),
    path("departments/", views.departments, name="departments"),
    path("applications/", views.applications, name="applications"),
    path("applications/<int:pk>/", views.vacation_detail, name="vacation_detail"),
    path("applications/<int:pk>/approve/", views.approve_vacation, name="approve_vacation"),
    path("applications/<int:pk>/reject/", views.reject_vacation, name="reject_vacation"),
    path("applications/<int:pk>/delete/", views.delete_vacation, name="delete_vacation"),
    path("analytics/", views.analytics, name="analytics"),
]
