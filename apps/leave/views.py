from datetime import date

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.formats import date_format

from apps.accounts.services import (
    can_access_analytics,
    can_access_applications,
    can_approve_leave_for_employee,
    can_initiate_schedule_change_for_item,
    can_review_schedule_change_request,
    can_view_employee,
    employee_required,
    get_current_employee,
    get_user_context,
    is_authorized_person_employee,
    is_hr_employee,
)
from apps.employees.services import update_context_with_departments
from apps.leave.models import (
    VACATION_TYPE_CHOICES,
    VacationPreference,
    VacationPreferenceCollection,
    VacationRequest,
    VacationScheduleChangeRequest,
    VacationScheduleItem,
)

from .forms import ScheduleChangeRequestCreateForm, VacationPreferenceResponseForm, VacationRequestCreateForm
from .services.calendar import get_calendar_redirect_url
from .services.constants import LEAVE_ADVANCE_MONTHS
from .services.dates import add_months_safe, get_chargeable_leave_days
from .services.ledger import get_employee_available_balance, get_employee_entitlement_source_preview
from .services.page_contexts import (
    build_analytics_page_context,
    build_applications_json_payload,
    build_applications_page_context,
    build_calendar_page_context,
    build_schedule_change_detail_context,
    build_vacation_detail_context,
)
from .services.preferences import (
    employee_can_join_preference_collection,
    finish_preference_collection,
    get_employee_preference_page_context,
    get_preference_planning_year,
    start_preference_collection,
    submit_employee_preferences,
)
from .services.querysets import get_vacation_requests_queryset
from .services.risk import (
    build_vacation_request_risk_explanation,
    calculate_schedule_change_risk,
    calculate_vacation_request_risk,
)
from .services.requests import (
    approve_vacation_request,
    create_vacation_request,
    delete_pending_vacation_request,
    reject_vacation_request,
)
from .services.schedule_changes import (
    approve_schedule_change_request,
    create_schedule_change_request,
    get_schedule_change_requests_queryset,
    is_manager_initiated_schedule_change,
    reject_schedule_change_request,
)
from .services.validation import validate_schedule_change_request, validate_vacation_request_for_employee


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


def _json_number(value):
    return float(value or 0)


def _serialize_entitlement_source_preview(preview):
    return {
        "entitlement_source_label": preview["label"],
        "entitlement_allocations": [
            {
                "working_year_number": row["working_year_number"],
                "period_label": row["period_label"],
                "period_start": row["period_start"].isoformat(),
                "period_end": row["period_end"].isoformat(),
                "days": _json_number(row["days"]),
                "balance_before": _json_number(row["balance_before"]),
                "balance_after": _json_number(row["balance_after"]),
            }
            for row in preview["allocations"]
        ],
    }


def _parse_preview_date(value, field_label):
    if not value:
        raise ValidationError(f"Выберите поле «{field_label}».")
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValidationError(f"Некорректная дата в поле «{field_label}».")


def _vacation_preview_message(vacation_type, start_date, employee, can_submit):
    available_from = add_months_safe(employee.date_joined, LEAVE_ADVANCE_MONTHS)
    if vacation_type == "paid" and start_date < available_from:
        return (
            f"Оплачиваемый отпуск доступен с {date_format(available_from, 'j E Y')}. "
            "Выберите дату начала не раньше этой даты."
        )
    if not can_submit:
        return ""
    if vacation_type == "paid":
        return "Заявку можно отправить: право на отпуск и баланс проверены на дату начала отпуска."
    if vacation_type == "study":
        return "Заявку можно отправить. Учебный отпуск не уменьшает оплачиваемый баланс."
    return "Заявку можно отправить. Неоплачиваемый отпуск не уменьшает оплачиваемый баланс."


def _vacation_preview_risk_message(risk_explanation):
    if risk_explanation["is_conflict"]:
        return f"Есть конфликт состава: {risk_explanation['short_reason']} {risk_explanation['recommended_action']}"
    if risk_explanation["level"] == VacationRequest.RISK_HIGH:
        return f"Высокий риск: {risk_explanation['short_reason']} {risk_explanation['recommended_action']}"
    if risk_explanation["level"] == VacationRequest.RISK_MEDIUM:
        return f"Средний риск: {risk_explanation['short_reason']}"
    return ""


def _build_vacation_preview_payload(employee, start_date, end_date, vacation_type):
    calendar_days = (end_date - start_date).days + 1 if end_date >= start_date else 0
    chargeable_days = get_chargeable_leave_days(start_date, end_date, vacation_type) if calendar_days else 0
    balance_today = get_employee_available_balance(employee)
    available_on_start = get_employee_available_balance(employee, as_of_date=start_date)
    available_from = add_months_safe(employee.date_joined, LEAVE_ADVANCE_MONTHS)
    risk_payload = calculate_vacation_request_risk(employee, start_date, end_date, vacation_type)
    risk_explanation = build_vacation_request_risk_explanation(employee, start_date, end_date, vacation_type)
    entitlement_source_preview = get_employee_entitlement_source_preview(
        employee,
        start_date,
        end_date,
        vacation_type,
    )
    can_submit = True
    message = ""

    try:
        validate_vacation_request_for_employee(employee, start_date, end_date, vacation_type)
    except ValidationError as exc:
        can_submit = False
        message = _vacation_preview_message(vacation_type, start_date, employee, False) or _validation_error_message(exc)

    if can_submit:
        message = _vacation_preview_risk_message(risk_explanation) or _vacation_preview_message(
            vacation_type,
            start_date,
            employee,
            True,
        )

    risk_label = dict(VacationRequest.RISK_CHOICES).get(risk_payload["risk_level"], "Низкий")
    payload = {
        "can_submit": can_submit,
        "message": message,
        "calendar_days": calendar_days,
        "chargeable_days": chargeable_days,
        "balance_today": _json_number(balance_today),
        "available_on_start": _json_number(available_on_start),
        "remaining_after_request": _json_number(risk_payload["balance_after_request"]),
        "available_from": available_from.isoformat(),
        "risk_label": risk_label,
        "risk_score": risk_payload["risk_score"],
        "risk_explanation": risk_explanation,
        "risk_short_reason": risk_explanation["short_reason"],
        "risk_recommended_action": risk_explanation["recommended_action"],
        "risk_is_conflict": risk_explanation["is_conflict"],
    }
    payload.update(_serialize_entitlement_source_preview(entitlement_source_preview))
    return payload


def _format_chargeable_days_delta(delta):
    if delta < 0:
        return f"Освободится {abs(delta):g} д."
    if delta > 0:
        return f"Добавится {delta:g} д."
    return "Без изменения"


def _empty_schedule_change_preview_payload(schedule_item, message):
    old_calendar_days = (schedule_item.end_date - schedule_item.start_date).days + 1
    return {
        "can_submit": False,
        "message": message,
        "old_calendar_days": old_calendar_days,
        "new_calendar_days": 0,
        "old_chargeable_days": _json_number(schedule_item.chargeable_days),
        "new_chargeable_days": 0,
        "chargeable_days_delta": 0,
        "chargeable_days_delta_label": "Выберите новые даты",
        "balance_after_change": _json_number(get_employee_available_balance(schedule_item.employee)),
        "risk_label": "Низкий",
        "risk_score": 0,
        "risk_explanation": {},
        "risk_short_reason": "",
        "risk_recommended_action": "",
        "risk_is_conflict": False,
    }


def _build_schedule_change_preview_payload(schedule_item, new_start_date, new_end_date):
    old_calendar_days = (schedule_item.end_date - schedule_item.start_date).days + 1
    new_calendar_days = (new_end_date - new_start_date).days + 1 if new_end_date >= new_start_date else 0
    old_chargeable_days = _json_number(schedule_item.chargeable_days)
    new_chargeable_days = (
        get_chargeable_leave_days(new_start_date, new_end_date, schedule_item.vacation_type)
        if new_calendar_days
        else 0
    )
    chargeable_days_delta = _json_number(new_chargeable_days) - old_chargeable_days
    can_submit = True
    message = "Перенос можно отправить: даты, баланс и пересечения проверены."

    try:
        validate_schedule_change_request(schedule_item, new_start_date, new_end_date)
    except ValidationError as exc:
        can_submit = False
        message = _validation_error_message(exc)

    risk_payload = calculate_schedule_change_risk(schedule_item, new_start_date, new_end_date) if new_calendar_days else {
        "risk_score": 0,
        "risk_level": VacationRequest.RISK_LOW,
        "balance_after_change": get_employee_available_balance(schedule_item.employee),
    }
    risk_explanation = (
        build_vacation_request_risk_explanation(
            schedule_item.employee,
            new_start_date,
            new_end_date,
            schedule_item.vacation_type,
            exclude_schedule_item_id=schedule_item.id,
        )
        if new_calendar_days
        else {}
    )
    risk_label = dict(VacationRequest.RISK_CHOICES).get(risk_payload["risk_level"], "Низкий")
    if can_submit:
        if risk_explanation.get("is_conflict"):
            message = "Перенос можно отправить, но есть конфликт состава."
        elif risk_payload["risk_level"] == VacationRequest.RISK_HIGH:
            message = "Перенос можно отправить, но риск высокий."

    return {
        "can_submit": can_submit,
        "message": message,
        "old_calendar_days": old_calendar_days,
        "new_calendar_days": new_calendar_days,
        "old_chargeable_days": old_chargeable_days,
        "new_chargeable_days": _json_number(new_chargeable_days),
        "chargeable_days_delta": chargeable_days_delta,
        "chargeable_days_delta_label": _format_chargeable_days_delta(chargeable_days_delta),
        "balance_after_change": _json_number(risk_payload["balance_after_change"]),
        "risk_label": risk_label,
        "risk_score": risk_payload["risk_score"],
        "risk_explanation": risk_explanation,
        "risk_short_reason": risk_explanation.get("short_reason", ""),
        "risk_recommended_action": risk_explanation.get("recommended_action", ""),
        "risk_is_conflict": risk_explanation.get("is_conflict", False),
    }


@employee_required
def vacation_request_preview(request):
    current_user = get_current_employee(request)
    if is_authorized_person_employee(current_user):
        return JsonResponse(
            {
                "can_submit": False,
                "message": "Уполномоченное лицо не создаёт заявки через календарь.",
            },
            status=403,
        )
    if request.method != "GET":
        return JsonResponse(
            {"can_submit": False, "message": "Проверка заявки доступна только GET-запросом."},
            status=405,
        )

    vacation_type = request.GET.get("vacation_type") or "paid"
    allowed_types = {choice[0] for choice in VACATION_TYPE_CHOICES}
    if vacation_type not in allowed_types:
        return JsonResponse(
            {
                "can_submit": False,
                "message": "Выберите корректный тип отпуска.",
                "calendar_days": 0,
                "chargeable_days": 0,
                "balance_today": _json_number(get_employee_available_balance(current_user)),
                "available_on_start": 0,
                "remaining_after_request": 0,
                "available_from": add_months_safe(current_user.date_joined, LEAVE_ADVANCE_MONTHS).isoformat(),
                "risk_label": "Низкий",
                "risk_score": 0,
                "entitlement_source_label": "Выберите корректный тип отпуска.",
                "entitlement_allocations": [],
            }
        )

    try:
        start_date = _parse_preview_date(request.GET.get("start_date"), "Дата начала")
        end_date = _parse_preview_date(request.GET.get("end_date"), "Дата окончания")
    except ValidationError as exc:
        return JsonResponse(
            {
                "can_submit": False,
                "message": _validation_error_message(exc),
                "calendar_days": 0,
                "chargeable_days": 0,
                "balance_today": _json_number(get_employee_available_balance(current_user)),
                "available_on_start": 0,
                "remaining_after_request": 0,
                "available_from": add_months_safe(current_user.date_joined, LEAVE_ADVANCE_MONTHS).isoformat(),
                "risk_label": "Низкий",
                "risk_score": 0,
                "entitlement_source_label": "Выберите даты, чтобы определить рабочий год списания.",
                "entitlement_allocations": [],
            }
        )

    return JsonResponse(_build_vacation_preview_payload(current_user, start_date, end_date, vacation_type))


@employee_required
def schedule_change_preview(request, item_id):
    current_employee = get_current_employee(request)
    schedule_item = get_object_or_404(
        VacationScheduleItem.objects.select_related("employee", "schedule"),
        pk=item_id,
    )
    if request.method != "GET":
        return JsonResponse(
            {"can_submit": False, "message": "Проверка переноса доступна только GET-запросом."},
            status=405,
        )
    if not can_initiate_schedule_change_for_item(current_employee, schedule_item):
        return JsonResponse(
            {
                "can_submit": False,
                "message": "У вас нет прав для создания переноса по этому отпуску.",
            },
            status=403,
        )

    try:
        new_start_date = _parse_preview_date(request.GET.get("new_start_date"), "Новая дата начала")
        new_end_date = _parse_preview_date(request.GET.get("new_end_date"), "Новая дата окончания")
    except ValidationError as exc:
        return JsonResponse(_empty_schedule_change_preview_payload(schedule_item, _validation_error_message(exc)))

    return JsonResponse(_build_schedule_change_preview_payload(schedule_item, new_start_date, new_end_date))


@employee_required
def graphics(request):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    current_user = get_current_employee(request)
    if is_authorized_person_employee(current_user):
        messages.error(request, "У вас нет прав для доступа к графику отпусков.")
        return redirect("applications")

    if request.method == "POST":
        form = VacationRequestCreateForm(_normalize_vacation_form_data(request.POST), employee=current_user)
        redirect_url = get_calendar_redirect_url(request)
        if form.is_valid():
            create_vacation_request(
                employee=current_user,
                start_date=form.cleaned_data["start_date"],
                end_date=form.cleaned_data["end_date"],
                vacation_type=form.cleaned_data["vacation_type"],
                reason=form.cleaned_data.get("reason", ""),
            )
            messages.success(request, "Заявка на отпуск успешно добавлена в график.")
        else:
            messages.error(request, _form_errors_to_messages(form) or "Не удалось создать заявку.")
        return redirect(redirect_url)

    context.update(build_calendar_page_context(current_user, request.GET))
    calendar_period_label = context["calendar_period_label"]
    calendar_period_description = context["calendar_period_description"]
    calendar_details = context["calendar_details"]
    calendar_month_details = context["calendar_month_details"]

    if request.method == "GET" and request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse(
            {
                "board_html": render_to_string("includes/calendar/board_content.html", context, request=request),
                "period_label": calendar_period_label,
                "period_description": calendar_period_description,
                "calendar_details": calendar_details,
                "calendar_month_details": calendar_month_details,
            }
        )

    return render(request, "calendar.html", context)


def _calendar_year_redirect(year):
    return f"{reverse('calendar')}?view=year&year={year}"


def _parse_collection_year(value):
    try:
        year = int(value)
    except (TypeError, ValueError):
        raise ValidationError("Выберите корректный год сбора пожеланий.")
    if year < 2000 or year > 2100:
        raise ValidationError("Выберите корректный год сбора пожеланий.")
    return year


def _parse_deadline(value):
    if not value:
        raise ValidationError("Укажите срок заполнения пожеланий.")
    try:
        deadline = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValidationError("Укажите корректный срок заполнения пожеланий.")
    if deadline < date.today():
        raise ValidationError("Срок заполнения не может быть в прошлом.")
    return deadline


@employee_required
def start_vacation_preferences_collection(request):
    current_employee = get_current_employee(request)
    if not is_hr_employee(current_employee):
        messages.error(request, "Запустить сбор пожеланий может только HR.")
        return redirect("calendar")
    if request.method != "POST":
        return redirect("calendar")

    try:
        year = _parse_collection_year(request.POST.get("year"))
        deadline = _parse_deadline(request.POST.get("deadline"))
    except ValidationError as exc:
        messages.error(request, _validation_error_message(exc))
        return redirect("calendar")

    planning_year = get_preference_planning_year()
    if year != planning_year:
        messages.error(request, f"Сбор пожеланий сейчас открывается только на {planning_year} год.")
        return redirect(_calendar_year_redirect(planning_year))

    demo_autofill = request.POST.get("demo_autofill") == "on"
    stats = start_preference_collection(
        year=year,
        deadline=deadline,
        actor=current_employee,
        demo_autofill=demo_autofill,
    )
    messages.success(
        request,
        (
            f"Сбор пожеланий на {year} год открыт. "
            f"Демо-ответов: {stats['demo_filled_count']}, "
            f"без пожеланий: {stats['demo_skipped_count']}, "
            f"ожидают ответа: {stats['notified_count']}."
        ),
    )
    return redirect(_calendar_year_redirect(year))


@employee_required
def finish_vacation_preferences_collection(request, year):
    current_employee = get_current_employee(request)
    if not is_hr_employee(current_employee):
        messages.error(request, "Завершить сбор пожеланий может только HR.")
        return redirect("calendar")
    if request.method != "POST":
        return redirect(_calendar_year_redirect(year))

    planning_year = get_preference_planning_year()
    if year != planning_year:
        messages.error(request, f"Сбор пожеланий сейчас ведётся только на {planning_year} год.")
        return redirect(_calendar_year_redirect(planning_year))

    try:
        finish_preference_collection(year=year, actor=current_employee)
    except VacationPreferenceCollection.DoesNotExist:
        messages.error(request, "Сбор пожеланий за этот год не найден.")
        return redirect(_calendar_year_redirect(year))

    messages.success(request, f"Сбор пожеланий на {year} год завершён.")
    return redirect(_calendar_year_redirect(year))


@employee_required
def vacation_preferences(request, year):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    current_employee = get_current_employee(request)
    if is_authorized_person_employee(current_employee):
        messages.error(request, "Уполномоченное лицо не заполняет пожелания по отпуску.")
        return redirect("applications")

    collection = get_object_or_404(VacationPreferenceCollection, year=year)
    if not employee_can_join_preference_collection(current_employee, year):
        messages.error(request, "Для этого года пожелания по отпуску вам недоступны.")
        return redirect("main")

    preference_context = get_employee_preference_page_context(current_employee, collection)
    primary = preference_context["primary_preference"]
    backup = preference_context["backup_preference"]
    initial = {
        "primary_start_date": primary.start_date if primary else None,
        "primary_end_date": primary.end_date if primary else None,
        "backup_start_date": backup.start_date if backup else None,
        "backup_end_date": backup.end_date if backup else None,
        "comment": (primary.comment if primary and primary.comment else backup.comment if backup else ""),
        "no_preferences": preference_context["preference_state"] == VacationPreference.STATUS_SKIPPED,
    }

    if request.method == "POST":
        if not preference_context["editable"]:
            messages.error(request, "Сбор пожеланий закрыт, изменить ответ уже нельзя.")
            return redirect("vacation_preferences", year=year)

        form = VacationPreferenceResponseForm(
            request.POST,
            employee=current_employee,
            collection=collection,
        )
        if form.is_valid():
            try:
                submit_employee_preferences(
                    collection=collection,
                    employee=current_employee,
                    primary_start=form.cleaned_data.get("primary_start_date"),
                    primary_end=form.cleaned_data.get("primary_end_date"),
                    backup_start=form.cleaned_data.get("backup_start_date"),
                    backup_end=form.cleaned_data.get("backup_end_date"),
                    comment=form.cleaned_data.get("comment", ""),
                    no_preferences=form.cleaned_data.get("no_preferences"),
                )
            except ValidationError as exc:
                messages.error(request, _validation_error_message(exc))
                return redirect("vacation_preferences", year=year)
            messages.success(request, "Пожелания по отпуску сохранены.")
            return redirect("vacation_preferences", year=year)
        messages.error(request, _form_errors_to_messages(form) or "Не удалось сохранить пожелания.")
    else:
        form = VacationPreferenceResponseForm(
            initial=initial,
            employee=current_employee,
            collection=collection,
        )

    if not preference_context["editable"]:
        for field in form.fields.values():
            field.disabled = True

    context.update(preference_context)
    context.update(
        {
            "form": form,
            "employee": current_employee,
            "preference_year": year,
            "sidebar_section": "calendar",
            "page_header_back_link": {
                "url": _calendar_year_redirect(year),
                "label": "К графику",
                "use_calendar_memory": True,
            },
        }
    )
    return render(request, "vacation_preferences.html", context)


@employee_required
def applications(request):
    current_employee = get_current_employee(request)
    if not can_access_applications(current_employee):
        messages.error(request, "Раздел заявок доступен только согласующим ролям и HR.")
        return redirect("main")

    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    page_context = build_applications_page_context(current_employee, request.GET)
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        payload = build_applications_json_payload(
            page_context["vacations"],
            page_context["change_requests"],
        )
        payload.update(
            {
                "change_requests_html": render_to_string(
                    "includes/applications/change_requests_list.html",
                    page_context,
                    request=request,
                ),
                "vacations_html": render_to_string(
                    "includes/applications/vacations_list.html",
                    page_context,
                    request=request,
                ),
            }
        )
        return JsonResponse(payload)

    context.update(page_context)
    return render(request, "applications.html", context)


@employee_required
def vacation_detail(request, pk):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    try:
        vacation = get_vacation_requests_queryset().get(pk=pk)
    except VacationRequest.DoesNotExist:
        messages.error(request, "Заявка удалена или больше недоступна.")
        return redirect("applications")
    current_employee = get_current_employee(request)
    if not can_view_employee(current_employee, vacation.employee):
        messages.error(request, "У вас нет прав для просмотра этой заявки.")
        return redirect("main")

    context.update(
        build_vacation_detail_context(
            vacation,
            current_employee,
            source=request.GET.get("from", ""),
            query_params=request.GET,
        )
    )
    return render(request, "vacation_detail.html", context)


@employee_required
def schedule_change_detail(request, pk):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    try:
        change_request = get_schedule_change_requests_queryset().get(pk=pk)
    except VacationScheduleChangeRequest.DoesNotExist:
        messages.error(request, "Перенос удалён или больше недоступен.")
        return redirect("applications")
    current_employee = get_current_employee(request)
    if not can_view_employee(current_employee, change_request.employee):
        messages.error(request, "У вас нет прав для просмотра этого переноса.")
        return redirect("main")

    context.update(
        build_schedule_change_detail_context(
            change_request,
            current_employee,
            source=request.GET.get("from", ""),
            query_params=request.GET,
        )
    )
    return render(request, "schedule_change_detail.html", context)


@employee_required
def approve_vacation(request, pk):
    vacation = get_object_or_404(get_vacation_requests_queryset(), pk=pk)
    current_employee = get_current_employee(request)

    if not can_approve_leave_for_employee(current_employee, vacation.employee):
        messages.error(request, "У вас нет прав для согласования этой заявки.")
        return redirect("vacation_detail", pk=pk)

    if request.method == "POST":
        try:
            approve_vacation_request(pk, reviewer=current_employee)
            messages.success(request, "Заявка успешно одобрена.")
        except ValidationError as exc:
            messages.error(request, _validation_error_message(exc))
    return redirect("applications")


@employee_required
def reject_vacation(request, pk):
    vacation = get_object_or_404(get_vacation_requests_queryset(), pk=pk)
    current_employee = get_current_employee(request)

    if not can_approve_leave_for_employee(current_employee, vacation.employee):
        messages.error(request, "У вас нет прав для согласования этой заявки.")
        return redirect("vacation_detail", pk=pk)

    if request.method == "POST":
        try:
            reject_vacation_request(pk, reviewer=current_employee)
            messages.error(request, "Заявка отклонена.")
        except ValidationError as exc:
            messages.error(request, _validation_error_message(exc))
    return redirect("applications")


@employee_required
def delete_vacation(request, pk):
    vacation = get_object_or_404(VacationRequest, pk=pk, status=VacationRequest.STATUS_PENDING)
    current_employee = get_current_employee(request)

    can_delete = vacation.employee_id == (current_employee.id if current_employee else None) or can_approve_leave_for_employee(
        current_employee,
        vacation.employee,
    )
    if not can_delete:
        messages.error(request, "У вас нет прав для удаления этой заявки.")
        return redirect("vacation_detail", pk=pk)

    if request.method == "POST":
        try:
            delete_pending_vacation_request(pk, actor=current_employee)
            messages.success(request, "Заявка успешно удалена.")
        except ValidationError as exc:
            messages.error(request, _validation_error_message(exc))
        return redirect("main")

    return redirect("vacation_detail", pk=pk)


@employee_required
def create_schedule_change(request, item_id):
    current_employee = get_current_employee(request)
    schedule_item = get_object_or_404(
        VacationScheduleItem.objects.select_related("employee", "schedule"),
        pk=item_id,
    )
    redirect_url = get_calendar_redirect_url(request)

    if request.method != "POST":
        return redirect(redirect_url)

    form = ScheduleChangeRequestCreateForm(request.POST, schedule_item=schedule_item)
    if not form.is_valid():
        messages.error(request, _form_errors_to_messages(form) or "Не удалось создать запрос переноса.")
        return redirect(redirect_url)

    try:
        change_request = create_schedule_change_request(
            schedule_item_id=schedule_item.id,
            requested_by=current_employee,
            new_start_date=form.cleaned_data["new_start_date"],
            new_end_date=form.cleaned_data["new_end_date"],
            reason=form.cleaned_data.get("reason", ""),
        )
        if is_manager_initiated_schedule_change(change_request):
            messages.success(request, "Предложение переноса отправлено сотруднику.")
        else:
            messages.success(request, "Запрос переноса отправлен на согласование.")
    except ValidationError as exc:
        messages.error(request, _validation_error_message(exc))
    return redirect(redirect_url)


@employee_required
def approve_schedule_change(request, pk):
    change_request = get_object_or_404(get_schedule_change_requests_queryset(), pk=pk)
    current_employee = get_current_employee(request)

    if not can_review_schedule_change_request(current_employee, change_request):
        if is_manager_initiated_schedule_change(change_request):
            messages.error(request, "Принять или отклонить предложение переноса может только сотрудник.")
        else:
            messages.error(request, "У вас нет прав для согласования этого переноса.")
        return redirect("schedule_change_detail", pk=pk)

    if request.method == "POST":
        try:
            approve_schedule_change_request(pk, reviewer=current_employee)
            if is_manager_initiated_schedule_change(change_request):
                messages.success(request, "Предложение переноса принято.")
            else:
                messages.success(request, "Перенос отпуска согласован.")
        except ValidationError as exc:
            messages.error(request, _validation_error_message(exc))
    return redirect("schedule_change_detail", pk=pk)


@employee_required
def reject_schedule_change(request, pk):
    change_request = get_object_or_404(get_schedule_change_requests_queryset(), pk=pk)
    current_employee = get_current_employee(request)

    if not can_review_schedule_change_request(current_employee, change_request):
        if is_manager_initiated_schedule_change(change_request):
            messages.error(request, "Принять или отклонить предложение переноса может только сотрудник.")
        else:
            messages.error(request, "У вас нет прав для согласования этого переноса.")
        return redirect("schedule_change_detail", pk=pk)

    if request.method == "POST":
        try:
            reject_schedule_change_request(pk, reviewer=current_employee)
            if is_manager_initiated_schedule_change(change_request):
                messages.success(request, "Предложение переноса отклонено.")
            else:
                messages.success(request, "Перенос отпуска отклонён.")
        except ValidationError as exc:
            messages.error(request, _validation_error_message(exc))
    return redirect("schedule_change_detail", pk=pk)


@employee_required
def analytics(request):
    current_employee = get_current_employee(request)
    if not can_access_analytics(current_employee):
        messages.error(request, "Раздел аналитики доступен только руководителям.")
        return redirect("main")

    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    context.update(build_analytics_page_context(current_employee, request.GET))
    return render(request, "analytics.html", context)
