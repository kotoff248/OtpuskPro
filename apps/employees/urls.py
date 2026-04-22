from django.urls import path

from . import views


urlpatterns = [
    path("main/", views.main, name="main"),
    path("employees/", views.employees, name="employees"),
    path("employee/<int:employee_id>/", views.employee_profile, name="employee_profile"),
    path("employee/<int:employee_id>/update/", views.update_employee, name="update_employee"),
    path("departments/", views.departments, name="departments"),
]


