import calendar
from datetime import date

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.services import (
    employee_required,
    get_current_employee,
    get_user_context,
    is_manager_user,
    manager_required,
)
from apps.employees.models import Departments
from apps.employees.services import update_context_with_departments
from apps.leave.models import VacationRequest

from .forms import VacationRequestCreateForm
from .services import (
    RUSSIAN_MONTH_NAMES,
    RUSSIAN_MONTH_SHORT_NAMES,
    WEEKDAY_SHORT_NAMES,
    approve_vacation_request,
    build_analytics_payload,
    build_calendar_base_data,
    build_calendar_rows,
    build_calendar_summary,
    delete_pending_vacation_request,
    enrich_vacation_request,
    get_calendar_redirect_url,
    get_employee_remaining_balance,
    get_vacation_requests_queryset,
    reject_vacation_request,
    serialize_vacation_request_row,
    sync_employee_vacation_metrics,
)


def _form_errors_to_messages(form):
    errors = []
    for field_errors in form.errors.values():
        errors.extend(field_errors)
    return " ".join(str(error) for error in errors)


def _validation_error_message(exc):
    return " ".join(exc.messages) if getattr(exc, "messages", None) else str(exc)


def _normalize_vacation_form_data(post_data):
    data = post_data.copy()
    if "type_vacation" in data and "vacation_type" not in data:
        data["vacation_type"] = data.get("type_vacation")
    return data


@employee_required
def graphics(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    current_user = get_current_employee(request)
    today = timezone.localdate()
    current_year = today.year

    selected_year = request.GET.get("year", current_year)
    selected_month = request.GET.get("month", today.month)
    calendar_view_mode = request.GET.get("view", "month")
    selected_employee_id = request.GET.get("employee")

    try:
        selected_year = int(selected_year)
    except (TypeError, ValueError):
        selected_year = current_year

    try:
        selected_month = int(selected_month)
    except (TypeError, ValueError):
        selected_month = today.month

    try:
        selected_employee_id = int(selected_employee_id) if selected_employee_id else None
    except (TypeError, ValueError):
        selected_employee_id = None

    if selected_month < 1 or selected_month > 12:
        selected_month = today.month
    if calendar_view_mode not in ("year", "month"):
        calendar_view_mode = "month"

    sync_employee_vacation_metrics(current_user)
    current_user.refresh_from_db()
    current_user_final_balance = get_employee_remaining_balance(current_user)

    if request.method == "POST":
        form = VacationRequestCreateForm(_normalize_vacation_form_data(request.POST), employee=current_user)
        redirect_url = get_calendar_redirect_url(request)
        if form.is_valid():
            request_obj = form.save(commit=False)
            request_obj.employee = current_user
            request_obj.status = VacationRequest.STATUS_PENDING
            request_obj.save()
            messages.success(request, "Заявка на отпуск успешно добавлена в график.")
        else:
            messages.error(request, _form_errors_to_messages(form) or "Не удалось создать заявку.")
        return redirect(redirect_url)

    employees, employee_day_status, employee_entries = build_calendar_base_data(selected_year)
    calendar_rows, calendar_details = build_calendar_rows(
        employees,
        employee_day_status,
        employee_entries,
        selected_year,
        selected_month,
        calendar_view_mode,
        today,
    )
    calendar_summary = build_calendar_summary(
        employee_entries,
        selected_year,
        selected_month,
        calendar_view_mode,
    )

    employee_ids = {row["employee_id"] for row in calendar_rows}
    if selected_employee_id not in employee_ids:
        selected_employee_id = current_user.id if current_user and current_user.id in employee_ids else None
    if selected_employee_id not in employee_ids and calendar_rows:
        selected_employee_id = calendar_rows[0]["employee_id"]

    selected_employee_detail = calendar_details.get(str(selected_employee_id)) if selected_employee_id else None
    available_years = list(range(current_year - 1, current_year + 5))
    calendar_period_label = (
        f"{RUSSIAN_MONTH_NAMES[selected_month - 1]} {selected_year}"
        if calendar_view_mode == "month"
        else f"График отпусков на {selected_year} год"
    )

    context.update(
        {
            "current_user": current_user,
            "current_user_final_balance": current_user_final_balance,
            "calendar_view_mode": calendar_view_mode,
            "calendar_period_label": calendar_period_label,
            "calendar_filters": {
                "selected_year": selected_year,
                "selected_month": selected_month,
                "available_years": available_years,
                "available_months": [
                    {"value": index + 1, "label": month_name}
                    for index, month_name in enumerate(RUSSIAN_MONTH_NAMES)
                ],
            },
            "calendar_summary": calendar_summary,
            "calendar_legend": [
                {"status": VacationRequest.STATUS_APPROVED, "label": "Одобрено"},
                {"status": VacationRequest.STATUS_PENDING, "label": "В ожидании"},
                {"status": VacationRequest.STATUS_REJECTED, "label": "Отклонено"},
            ],
            "calendar_rows": calendar_rows,
            "calendar_details": calendar_details,
            "selected_employee_id": selected_employee_id,
            "selected_employee_detail": selected_employee_detail,
            "selected_month_name": RUSSIAN_MONTH_NAMES[selected_month - 1],
            "year_short_headers": RUSSIAN_MONTH_SHORT_NAMES,
            "month_day_headers": [
                {
                    "day": day,
                    "weekday": WEEKDAY_SHORT_NAMES[date(selected_year, selected_month, day).weekday()],
                    "is_weekend": date(selected_year, selected_month, day).weekday() >= 5,
                    "is_today": date(selected_year, selected_month, day) == today,
                }
                for day in range(1, calendar.monthrange(selected_year, selected_month)[1] + 1)
            ],
            "today_iso": today.isoformat(),
        }
    )
    return render(request, "calendar.html", context)


@employee_required
@manager_required
def applications(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    status_filter = request.GET.get("status", "all")
    department_id = request.GET.get("department", "all")
    requests_qs = get_vacation_requests_queryset().order_by("-created_at")

    if status_filter in {
        VacationRequest.STATUS_APPROVED,
        VacationRequest.STATUS_PENDING,
        VacationRequest.STATUS_REJECTED,
    }:
        requests_qs = requests_qs.filter(status=status_filter)

    if department_id != "all":
        try:
            requests_qs = requests_qs.filter(employee__department_id=int(department_id))
        except (TypeError, ValueError):
            department_id = "all"

    vacations = [enrich_vacation_request(request_obj) for request_obj in requests_qs]

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"vacations": [serialize_vacation_request_row(vacation) for vacation in vacations]})

    context.update(
        {
            "vacations": vacations,
            "selected_status": status_filter,
            "selected_department": str(department_id),
        }
    )
    return render(request, "applications.html", context)


@employee_required
def vacation_detail(request, pk):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    vacation = get_object_or_404(get_vacation_requests_queryset(), pk=pk)
    enrich_vacation_request(vacation)

    current_employee = get_current_employee(request)
    current_employee_id = current_employee.id if current_employee else None
    is_manager = is_manager_user(request.user)
    if not is_manager and vacation.employee.id != current_employee_id:
        messages.error(request, "У вас нет прав для просмотра чужой заявки.")
        return redirect("main")

    can_delete = vacation.status == VacationRequest.STATUS_PENDING and (
        vacation.employee.id == (current_employee.id if current_employee else None) or is_manager
    )
    current_balance = get_employee_remaining_balance(vacation.employee)

    context.update(
        {
            "vacation": vacation,
            "employee": vacation.employee,
            "status": vacation.status,
            "status_label": vacation.status_label,
            "status_icon": vacation.status_icon,
            "status_css_class": vacation.status_css_class,
            "current_balance": current_balance,
            "is_manager": is_manager,
            "can_delete": can_delete,
        }
    )
    return render(request, "vacation_detail.html", context)


@employee_required
@manager_required
def approve_vacation(request, pk):
    if request.method == "POST":
        try:
            approve_vacation_request(pk)
            messages.success(request, "Заявка успешно одобрена.")
        except ValidationError as exc:
            messages.error(request, _validation_error_message(exc))
    return redirect("applications")


@employee_required
@manager_required
def reject_vacation(request, pk):
    if request.method == "POST":
        try:
            reject_vacation_request(pk)
            messages.error(request, "Заявка отклонена.")
        except ValidationError as exc:
            messages.error(request, _validation_error_message(exc))
    return redirect("applications")


@employee_required
def delete_vacation(request, pk):
    vacation = get_object_or_404(VacationRequest, pk=pk, status=VacationRequest.STATUS_PENDING)
    current_employee = get_current_employee(request)
    is_manager = is_manager_user(request.user)

    if vacation.employee.id != (current_employee.id if current_employee else None) and not is_manager:
        messages.error(request, "У вас нет прав для удаления этой заявки.")
        return redirect("vacation_detail", pk=pk)

    if request.method == "POST":
        try:
            delete_pending_vacation_request(pk)
            messages.success(request, "Заявка успешно удалена.")
        except ValidationError as exc:
            messages.error(request, _validation_error_message(exc))
        return redirect("main")

    return redirect("vacation_detail", pk=pk)


@employee_required
@manager_required
def analytics(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    context.update({"departments": Departments.objects.all()})
    context.update(build_analytics_payload())
    return render(request, "analytics.html", context)
