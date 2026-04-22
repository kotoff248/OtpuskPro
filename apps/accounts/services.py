from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.shortcuts import redirect

from apps.employees.models import Employees


MANAGERS_GROUP_NAME = "Managers"


def normalize_employee_login(value):
    return (value or "").strip()


def default_employee_login(employee_id):
    return f"employee_{employee_id}"


def get_manager_group():
    group, _ = Group.objects.get_or_create(name=MANAGERS_GROUP_NAME)
    return group


def is_manager_user(user):
    return user.is_authenticated and user.groups.filter(name=MANAGERS_GROUP_NAME).exists()


def get_current_employee(request):
    if not request.user.is_authenticated:
        return None

    employee = getattr(request.user, "employee_profile", None)
    if employee is None:
        employee = Employees.objects.filter(user=request.user).first()
    return employee


def sync_employee_user(employee, raw_password=None):
    username = normalize_employee_login(employee.login)
    if not username:
        if employee.pk is None:
            raise ValueError("Employee must be saved before syncing user data.")
        username = default_employee_login(employee.pk)

    User = get_user_model()
    existing_user = employee.user
    if existing_user is None:
        existing_user = User.objects.filter(username=username).first()
        if existing_user is None:
            existing_user = User(username=username, is_active=True)
        employee.user = existing_user

    existing_user.username = username
    existing_user.first_name = employee.full_name[:150]
    existing_user.last_name = ""
    existing_user.is_active = True
    existing_user.is_staff = employee.is_manager

    if raw_password is not None and raw_password != "":
        existing_user.set_password(raw_password)
    elif not existing_user.password:
        existing_user.set_unusable_password()

    existing_user.save()

    manager_group = get_manager_group()
    if employee.is_manager:
        existing_user.groups.add(manager_group)
    else:
        existing_user.groups.remove(manager_group)

    updates = []
    if employee.user_id != existing_user.id:
        employee.user = existing_user
        updates.append("user")
    if employee.login != username:
        employee.login = username
        updates.append("login")
    if updates:
        employee.save(update_fields=updates)

    return existing_user


def get_user_context(request):
    employee = get_current_employee(request)
    if employee is not None:
        employee_name = employee.full_name
        last_name = employee.last_name
        initials = "".join(f"{part[0].upper()}." for part in [employee.first_name, employee.middle_name] if part)
    else:
        employee_name = request.user.get_username()
        name_parts = employee_name.split()
        last_name = name_parts[0] if name_parts else ""
        initials = "".join(f"{name[0].upper()}." for name in name_parts[1:])

    is_manager = is_manager_user(request.user)
    role = "руководитель" if is_manager else "сотрудник"
    return {
        "employee_name": employee_name,
        "last_name": last_name,
        "initials": initials,
        "role": role,
        "is_manager": is_manager,
    }


def manager_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if is_manager_user(request.user):
            return view_func(request, *args, **kwargs)

        messages.error(request, "У вас нет прав для доступа к этой странице.")
        return redirect("main")

    return _wrapped_view


def employee_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        employee = get_current_employee(request)
        if request.user.is_authenticated and employee is not None:
            return view_func(request, *args, **kwargs)

        return redirect("login")

    return _wrapped_view
