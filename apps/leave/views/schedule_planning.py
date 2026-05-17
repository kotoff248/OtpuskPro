from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import (
    redirect,
    render,
)
from django.urls import reverse

from apps.accounts.services import (
    employee_required,
    get_current_employee,
    get_user_context,
    is_authorized_person_employee,
    is_enterprise_head_employee,
    is_hr_employee,
)
from apps.employees.services import update_context_with_departments
from apps.leave.services.schedule_planning import (
    build_schedule_planning_page_context,
    can_access_schedule_planning,
    get_schedule_planning_year,
    schedule_planning_url,
)
from apps.leave.services.planning_cycles import start_next_planning_cycle
from apps.leave.views.common import (
    _validation_error_message,
    _safe_next_url,
)


@employee_required
def schedule_planning_current(request):
    target_url = reverse("schedule_planning", args=[get_schedule_planning_year()])
    query = request.GET.urlencode()
    if query:
        target_url = f"{target_url}?{query}"
    return redirect(target_url)


@employee_required
def schedule_planning(request, year):
    current_employee = get_current_employee(request)
    if not can_access_schedule_planning(current_employee):
        messages.error(request, "Планирование графика доступно только участникам подготовки годового графика.")
        if is_authorized_person_employee(current_employee):
            return redirect("applications")
        return redirect("calendar")

    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    context.update(build_schedule_planning_page_context(year, current_employee, request.GET))
    context.update(
        {
            "planning_subtitle": f"Подготовка графика отпусков на {year} год",
            "sidebar_section": "schedule_planning",
        }
    )
    return render(request, "vacation_schedule_planning.html", context)


@employee_required
def start_next_schedule_planning_cycle(request, year):
    current_employee = get_current_employee(request)
    redirect_after_action = _safe_next_url(request, schedule_planning_url(year))
    if request.method != "POST":
        return redirect(schedule_planning_url(year))
    if not (is_hr_employee(current_employee) or is_enterprise_head_employee(current_employee)):
        messages.error(request, "Начать следующий год планирования может только HR или руководитель предприятия.")
        if is_authorized_person_employee(current_employee):
            return redirect("applications")
        return redirect("calendar")

    try:
        result = start_next_planning_cycle(year=year, actor=current_employee)
    except ValidationError as exc:
        messages.error(request, _validation_error_message(exc))
        return redirect(redirect_after_action)

    messages.success(request, f"Планирование графика на {result['year']} год открыто.")
    return redirect(_safe_next_url(request, schedule_planning_url(result["year"])))
