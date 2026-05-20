from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.conf import settings
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.core.services.demo_seed.constants import DEFAULT_PASSWORD
from apps.employees.models import Employees

from .services import (
    can_use_management_login,
    get_current_employee,
    is_authorized_person_employee,
)


DEMO_LOGIN_HINT_ITEMS = [
    {
        "role": "Сотрудник",
        "login": "employ_1",
        "hint": "Также доступны employ_2 ... employ_100",
        "mode": "Вход сотрудника",
        "icon": "person",
    },
    {
        "role": "HR",
        "login": "hr_1",
        "hint": "Полный доступ к планированию и заявкам",
        "mode": "Вход управленца",
        "icon": "manage_accounts",
    },
    {
        "role": "Руководитель отдела",
        "login": "manager_1",
        "hint": "Согласование сотрудников своего отдела",
        "mode": "Вход управленца",
        "icon": "supervisor_account",
    },
    {
        "role": "Руководитель предприятия",
        "login": "director_1",
        "hint": "Финальное согласование графика",
        "mode": "Вход управленца",
        "icon": "corporate_fare",
    },
    {
        "role": "Уполномоченное лицо",
        "login": "admin_1",
        "hint": "Служебное согласование заявок руководителя",
        "mode": "Вход управленца",
        "icon": "verified_user",
    },
]


def _build_demo_login_hint():
    if not getattr(settings, "SHOW_DEMO_LOGIN_HINTS", settings.DEBUG):
        return None
    return {
        "password": DEFAULT_PASSWORD,
        "items": DEMO_LOGIN_HINT_ITEMS,
    }


def login_view(request):
    error = None
    if request.user.is_authenticated:
        if get_current_employee(request) is not None:
            return redirect("main")
        auth_logout(request)

    if request.method == "POST":
        login_value = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user_type = request.POST.get("user_type", "")

        employee = Employees.objects.select_related("user").filter(login__iexact=login_value).first()
        if employee is None or not getattr(employee, "is_active_employee", True):
            error = "Пользователь не найден"
        else:
            if employee.user is None:
                error = "Пользователь не найден"
            else:
                user = authenticate(request, username=employee.user.username, password=password)
                if user is None:
                    error = "Неверный пароль"
                elif user_type == "management" and not can_use_management_login(employee):
                    error = "Неверный тип пользователя"
                elif user_type == "employee" and can_use_management_login(employee):
                    error = "Неверный тип пользователя"
                else:
                    auth_login(request, user)
                    if is_authorized_person_employee(employee):
                        return redirect("applications")
                    return redirect("main")

    return render(
        request,
        "login.html",
        {
            "error": error,
            "demo_login_hint": _build_demo_login_hint(),
        },
    )


def logout_view(request):
    auth_logout(request)
    return redirect(f"{reverse('login')}?signed_out=1")
