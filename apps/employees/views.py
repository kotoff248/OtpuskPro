from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from apps.accounts.services import (
    can_access_departments_page,
    can_access_staffing_page,
    can_delete_employee,
    can_edit_employee_data,
    can_edit_staffing_rules,
    can_view_employee,
    employee_required,
    get_accessible_departments,
    get_current_employee,
    get_user_context,
    is_authorized_person_employee,
    is_hr_employee,
)
from apps.employees.models import (
    DepartmentCoverageRule,
    Departments,
    EmployeePosition,
    Employees,
    ProductionGroup,
    ProductionGroupSubstitutionRule,
)

from .forms import DepartmentCreateForm, EmployeeCreateForm, EmployeeUpdateForm
from .page_contexts import (
    build_department_detail_page_context,
    build_departments_page_context,
    build_departments_queryset,
    build_employee_profile_context,
    build_employees_page_context,
    build_main_profile_context,
    serialize_departments_queryset,
)
from .services import archive_employee, update_context_with_departments


def _form_errors_to_messages(form):
    errors = []
    for field_errors in form.errors.values():
        errors.extend(field_errors)
    return " ".join(str(error) for error in errors)


def _normalize_employee_form_data(post_data):
    data = post_data.copy()
    field_map = {
        "employee_last_name": "last_name",
        "employee_first_name": "first_name",
        "employee_middle_name": "middle_name",
        "employee_position_id": "employee_position",
        "employee_date_joined": "date_joined",
        "employee_vacation_days": "annual_paid_leave_days",
        "employee_annual_paid_leave_days": "annual_paid_leave_days",
        "vacation_days": "annual_paid_leave_days",
        "employee_department": "department",
        "employee_role": "role",
    }
    for old_name, new_name in field_map.items():
        if old_name in data and new_name not in data:
            data[new_name] = data.get(old_name)
    return data


def _get_employee_redirect_response(request, employee_id):
    next_path = request.POST.get("next_path")
    if next_path and url_has_allowed_host_and_scheme(
        next_path,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_path)
    return redirect("employee_profile", employee_id=employee_id)


@employee_required
def main(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    employee = get_current_employee(request)
    if is_authorized_person_employee(employee):
        return redirect("applications")

    context.update(build_main_profile_context(employee))
    return render(request, "main.html", context)


@employee_required
def employee_profile(request, employee_id):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    current_employee = get_current_employee(request)
    if is_authorized_person_employee(current_employee):
        return redirect("applications")
    employee = get_object_or_404(
        Employees.objects.select_related(
            "department",
            "managed_department",
            "employee_position",
            "employee_position__production_group",
        ).exclude(role__in=Employees.SERVICE_ROLES),
        id=employee_id,
    )

    if not can_view_employee(current_employee, employee):
        messages.error(request, "У вас нет прав для просмотра этого профиля.")
        return redirect("main")

    context.update(
        build_employee_profile_context(
            current_employee,
            employee,
            source=request.GET.get("from", ""),
            return_to=request.GET.get("return_to", ""),
            vacation_id=request.GET.get("vacation_id", ""),
            query_params=request.GET,
        )
    )
    return render(request, "employee_profile.html", context)


@employee_required
def update_employee(request, employee_id):
    current_employee = get_current_employee(request)
    if not can_edit_employee_data(current_employee):
        messages.error(request, "Только HR может редактировать карточки сотрудников.")
        return redirect("main")

    employee = get_object_or_404(Employees.objects.exclude(role__in=Employees.SERVICE_ROLES), id=employee_id)
    if not employee.is_active_employee:
        messages.error(request, "Архивного сотрудника нельзя редактировать.")
        return redirect("employee_profile", employee_id=employee_id)

    if request.method != "POST":
        return redirect("employee_profile", employee_id=employee_id)

    redirect_response = _get_employee_redirect_response(request, employee_id)
    form = EmployeeUpdateForm(_normalize_employee_form_data(request.POST), instance=employee)
    if not form.is_valid():
        messages.error(request, _form_errors_to_messages(form) or "Не удалось обновить данные сотрудника.")
        return redirect_response

    updated_employee = form.save()
    if form.cleaned_data.get("password") and request.user.pk == updated_employee.user_id and updated_employee.user is not None:
        update_session_auth_hash(request, updated_employee.user)

    messages.success(request, "Данные сотрудника обновлены.")
    return redirect_response


@employee_required
def delete_employee(request, employee_id):
    current_employee = get_current_employee(request)
    employee = get_object_or_404(
        Employees.objects.select_related("user").exclude(role__in=Employees.SERVICE_ROLES),
        id=employee_id,
    )

    if request.method != "POST":
        return redirect("employee_profile", employee_id=employee_id)

    if not can_delete_employee(current_employee, employee):
        messages.error(request, "У вас нет прав для удаления этого сотрудника.")
        return redirect("employee_profile", employee_id=employee_id)

    archive_employee(employee)
    messages.success(request, "Сотрудник удалён из активного состава.")
    return redirect("employees")


@employee_required
def employees(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    current_employee = get_current_employee(request)
    if is_authorized_person_employee(current_employee):
        messages.error(request, "У вас нет прав для доступа к списку сотрудников.")
        return redirect("applications")
    can_edit = can_edit_employee_data(current_employee)

    if request.method == "POST" and not can_edit:
        messages.error(request, "Только HR может добавлять сотрудников.")
        return redirect("employees")

    if request.method == "POST" and can_edit and ("last_name" in request.POST or "employee_last_name" in request.POST):
        form = EmployeeCreateForm(_normalize_employee_form_data(request.POST))
        if form.is_valid():
            form.save()
            messages.success(request, "Сотрудник создан.")
        else:
            messages.error(request, _form_errors_to_messages(form) or "Не удалось создать сотрудника.")
        return redirect("employees")

    employees_context = build_employees_page_context(current_employee, request.GET, request.session)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"employees": employees_context["employees"]})

    employees_context.update(
        {
            "can_manage_employees": can_edit,
            "show_manager_fields": can_edit,
        }
    )
    context.update(employees_context)
    return render(request, "employees.html", context)


@employee_required
def departments(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    current_employee = get_current_employee(request)
    can_create_department = is_hr_employee(current_employee)

    if not can_access_departments_page(current_employee):
        messages.error(request, "У вас нет прав для доступа к разделу отделов.")
        return redirect("main")

    department_modal_open = False
    if request.method == "POST":
        if not can_create_department:
            messages.error(request, "Только HR может создавать отделы.")
            return redirect("departments")

        department_create_form = DepartmentCreateForm(request.POST)
        if department_create_form.is_valid():
            department_create_form.save()
            messages.success(request, "Отдел создан.")
            return redirect("departments")

        department_modal_open = True
        messages.error(request, _form_errors_to_messages(department_create_form) or "Не удалось создать отдел.")
    else:
        department_create_form = DepartmentCreateForm()

    departments_qs = build_departments_queryset(current_employee)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"departments": serialize_departments_queryset(departments_qs)})

    context.update(
        build_departments_page_context(
            departments_qs,
            department_create_form,
            department_modal_open,
            can_create_department,
        )
    )
    return render(request, "departments.html", context)


@employee_required
def department_detail(request, department_id):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    current_employee = get_current_employee(request)

    if not can_access_departments_page(current_employee):
        messages.error(request, "У вас нет прав для доступа к разделу отделов.")
        return redirect("main")

    department = build_departments_queryset(current_employee).filter(id=department_id).first()
    if department is None:
        messages.error(request, "Отдел недоступен или не найден.")
        return redirect("departments")

    context.update(
        build_department_detail_page_context(
            current_employee,
            department,
            request.GET,
            request.session,
        )
    )
    return render(request, "department_detail.html", context)


def _get_staffing_departments(current_employee):
    return get_accessible_departments(current_employee).select_related(
        "head",
        "deputy",
    ).prefetch_related(
        "production_groups__positions",
        "coverage_rules__production_group",
        "substitution_rules__source_group",
        "substitution_rules__substitute_group",
        "employees",
    )


def _staffing_department_or_none(current_employee, department_id):
    try:
        department_id = int(department_id)
    except (TypeError, ValueError):
        return None
    return _get_staffing_departments(current_employee).filter(id=department_id).first()


def _staffing_employee_or_none(department, employee_id):
    if not employee_id:
        return None
    try:
        employee_id = int(employee_id)
    except (TypeError, ValueError):
        return None
    return Employees.objects.filter(
        id=employee_id,
        department=department,
        is_active_employee=True,
    ).exclude(role__in=Employees.SERVICE_ROLES).first()


def _staffing_group_or_none(department, group_id):
    try:
        group_id = int(group_id)
    except (TypeError, ValueError):
        return None
    return ProductionGroup.objects.filter(id=group_id, department=department).first()


def _staffing_substitution_or_none(department, substitution_id):
    try:
        substitution_id = int(substitution_id)
    except (TypeError, ValueError):
        return None
    return ProductionGroupSubstitutionRule.objects.filter(id=substitution_id, department=department).first()


def _positive_small_int(value, default=1, minimum=1):
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return default


@transaction.atomic
def _delete_staffing_department(department):
    Employees.objects.filter(department=department).update(department=None, employee_position=None)
    Employees.objects.filter(employee_position__department=department).update(employee_position=None)
    EmployeePosition.objects.filter(department=department).delete()
    department.delete()


def _handle_staffing_post(request, current_employee):
    action = request.POST.get("action")
    department = _staffing_department_or_none(current_employee, request.POST.get("department_id"))
    if department is None:
        messages.error(request, "Выберите доступный отдел.")
        return

    if action == "delete_department":
        department_name = department.name
        _delete_staffing_department(department)
        messages.success(request, f'Отдел "{department_name}" удалён.')
        return

    if action == "update_deputy":
        department.deputy = _staffing_employee_or_none(department, request.POST.get("deputy_id"))
        department.save(update_fields=["deputy"])
        messages.success(request, "Заместитель руководителя отдела обновлён.")
        return

    if action == "create_group":
        name = " ".join((request.POST.get("name") or "").split())
        code = " ".join((request.POST.get("code") or "").split())
        if not name:
            messages.error(request, "Введите название производственной группы.")
            return
        ProductionGroup.objects.get_or_create(
            department=department,
            name=name,
            defaults={"code": code},
        )
        messages.success(request, "Производственная группа добавлена.")
        return

    if action == "create_position":
        title = " ".join((request.POST.get("title") or "").split())
        production_group = _staffing_group_or_none(department, request.POST.get("production_group_id"))
        if not title or production_group is None:
            messages.error(request, "Выберите группу и введите должность.")
            return
        EmployeePosition.objects.get_or_create(
            department=department,
            title=title,
            defaults={"production_group": production_group},
        )
        messages.success(request, "Должность добавлена в справочник.")
        return

    if action == "save_coverage":
        production_group = _staffing_group_or_none(department, request.POST.get("production_group_id"))
        if production_group is None:
            messages.error(request, "Выберите производственную группу.")
            return
        try:
            min_staff_required = max(0, int(request.POST.get("min_staff_required", 1)))
            max_absent = max(0, int(request.POST.get("max_absent", 1)))
            criticality_level = min(5, max(1, int(request.POST.get("criticality_level", 3))))
        except (TypeError, ValueError):
            messages.error(request, "Проверьте числовые значения правила покрытия.")
            return
        DepartmentCoverageRule.objects.update_or_create(
            department=department,
            production_group=production_group,
            defaults={
                "min_staff_required": min_staff_required,
                "max_absent": max_absent,
                "criticality_level": criticality_level,
            },
        )
        messages.success(request, "Правило покрытия сохранено.")
        return

    if action == "create_substitution":
        source_group = _staffing_group_or_none(department, request.POST.get("source_group_id"))
        substitute_group = _staffing_group_or_none(department, request.POST.get("substitute_group_id"))
        max_covered_absences = _positive_small_int(request.POST.get("max_covered_absences"), default=1)
        if source_group is None or substitute_group is None:
            messages.error(request, "Выберите обе группы для замещения.")
            return
        if source_group.id == substitute_group.id:
            messages.error(request, "Группа не может замещать саму себя.")
            return
        ProductionGroupSubstitutionRule.objects.update_or_create(
            department=department,
            source_group=source_group,
            substitute_group=substitute_group,
            defaults={"max_covered_absences": max_covered_absences},
        )
        messages.success(request, "Правило замещения добавлено.")
        return

    if action == "update_substitution":
        substitution = _staffing_substitution_or_none(department, request.POST.get("substitution_id"))
        if substitution is None:
            messages.error(request, "Выберите правило замещения.")
            return
        substitution.max_covered_absences = _positive_small_int(request.POST.get("max_covered_absences"), default=1)
        substitution.save(update_fields=["max_covered_absences"])
        messages.success(request, "Лимит замещения обновлён.")
        return

    if action == "delete_substitution":
        substitution = _staffing_substitution_or_none(department, request.POST.get("substitution_id"))
        if substitution is None:
            messages.error(request, "Выберите правило замещения.")
            return
        substitution.delete()
        messages.success(request, "Правило замещения удалено.")
        return

    messages.error(request, "Неизвестное действие на странице правил состава.")


@employee_required
def staffing_rules(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    current_employee = get_current_employee(request)
    if not can_access_staffing_page(current_employee):
        messages.error(request, "У вас нет прав для доступа к правилам состава.")
        return redirect("main")

    can_edit = can_edit_staffing_rules(current_employee)
    if request.method == "POST":
        if not can_edit:
            messages.error(request, "Редактировать правила состава могут HR и руководитель предприятия.")
            return redirect("staffing_rules")

        if request.POST.get("action") == "set_enterprise_deputy":
            deputy_id = request.POST.get("enterprise_deputy_id")
            Employees.objects.update(is_enterprise_deputy=False)
            if deputy_id:
                deputy = Employees.objects.filter(
                    id=deputy_id,
                    is_active_employee=True,
                ).exclude(role__in=Employees.SERVICE_ROLES).first()
                if deputy is not None:
                    deputy.is_enterprise_deputy = True
                    deputy.save(update_fields=["is_enterprise_deputy"])
            messages.success(request, "Заместитель руководителя предприятия обновлён.")
        else:
            _handle_staffing_post(request, current_employee)
        return redirect("staffing_rules")

    departments_qs = _get_staffing_departments(current_employee)
    departments = list(departments_qs)
    active_employees = Employees.objects.select_related(
        "department",
        "employee_position",
        "employee_position__production_group",
    ).filter(
        department__in=departments,
        is_active_employee=True,
    ).exclude(role__in=Employees.SERVICE_ROLES).order_by(
        "department__name",
        "last_name",
        "first_name",
        "middle_name",
    )
    employees_by_department = {}
    for employee in active_employees:
        employees_by_department.setdefault(employee.department_id, []).append(employee)
    for department in departments:
        department.staffing_employees = employees_by_department.get(department.id, [])

    context.update(
        {
            "sidebar_section": "staffing",
            "staffing_departments": departments,
            "can_edit_staffing": can_edit,
            "enterprise_deputy_candidates": list(active_employees),
            "current_enterprise_deputy": Employees.objects.filter(
                is_enterprise_deputy=True,
                is_active_employee=True,
            ).exclude(role__in=Employees.SERVICE_ROLES).first(),
        }
    )
    return render(request, "staffing.html", context)
