from django.urls import path

from apps.leave.views import applications


urlpatterns = [
    path("applications/", applications.applications, name="applications"),
    path("applications/<int:pk>/", applications.vacation_detail, name="vacation_detail"),
    path("applications/<int:pk>/approve/", applications.approve_vacation, name="approve_vacation"),
    path("applications/<int:pk>/reject/", applications.reject_vacation, name="reject_vacation"),
    path("applications/<int:pk>/delete/", applications.delete_vacation, name="delete_vacation"),
    path(
        "calendar/schedule-items/<int:item_id>/transfer/",
        applications.create_schedule_change,
        name="schedule_change_request_create",
    ),
    path("applications/transfers/<int:pk>/", applications.schedule_change_detail, name="schedule_change_detail"),
    path(
        "applications/transfers/<int:pk>/approve/",
        applications.approve_schedule_change,
        name="schedule_change_approve",
    ),
    path(
        "applications/transfers/<int:pk>/reject/",
        applications.reject_schedule_change,
        name="schedule_change_reject",
    ),
    path(
        "applications/urgent-closures/<int:pk>/",
        applications.urgent_closure_detail,
        name="urgent_closure_detail",
    ),
    path(
        "applications/urgent-closures/<int:pk>/manager-approve/",
        applications.approve_urgent_closure_manager,
        name="urgent_closure_manager_approve",
    ),
    path(
        "applications/urgent-closures/<int:pk>/employee-accept/",
        applications.accept_urgent_closure_employee,
        name="urgent_closure_employee_accept",
    ),
    path(
        "applications/urgent-closures/<int:pk>/employee-propose/",
        applications.propose_urgent_closure_employee,
        name="urgent_closure_employee_propose",
    ),
    path(
        "applications/urgent-closures/<int:pk>/employee-preview/",
        applications.urgent_closure_employee_preview,
        name="urgent_closure_employee_preview",
    ),
    path(
        "applications/urgent-closures/<int:pk>/finalize/",
        applications.finalize_urgent_closure_hr,
        name="urgent_closure_finalize",
    ),
    path(
        "applications/urgent-closures/<int:pk>/reject/",
        applications.reject_urgent_closure_request,
        name="urgent_closure_reject",
    ),
]
