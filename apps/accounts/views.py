from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.shortcuts import redirect, render

from apps.employees.models import Employees

from .services import get_current_employee, is_management_user


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
        if employee is None or employee.user is None:
            error = "Пользователь не найден"
        else:
            user = authenticate(request, username=employee.user.username, password=password)
            if user is None:
                error = "Неверный пароль"
            elif user_type == "management" and not is_management_user(user):
                error = "Неверный тип пользователя"
            elif user_type == "employee" and is_management_user(user):
                error = "Неверный тип пользователя"
            else:
                auth_login(request, user)
                return redirect("main")

    return render(request, "login.html", {"error": error})


def logout_view(request):
    auth_logout(request)
    return redirect("login")
