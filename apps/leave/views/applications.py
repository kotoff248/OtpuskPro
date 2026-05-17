from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.template.loader import render_to_string

from apps.accounts.services import (
    can_access_applications,
    can_approve_leave_for_employee,
    can_review_schedule_change_request,
    can_view_employee,
    employee_required,
    get_current_employee,
    get_user_context,
)
from apps.employees.services import update_context_with_departments
from apps.leave.models import (
    VacationRequest,
    VacationScheduleChangeRequest,
    VacationScheduleItem,
    VacationUrgentClosureRequest,
)
from apps.leave.forms import ScheduleChangeRequestCreateForm
from apps.leave.services.calendar import get_calendar_redirect_url
from apps.leave.services.page_contexts import (
    build_applications_json_payload,
    build_applications_page_context,
    build_schedule_change_detail_context,
    build_urgent_closure_detail_context,
    build_vacation_detail_context,
)
from apps.leave.services.querysets import get_vacation_requests_queryset
from apps.leave.services.requests import (
    approve_vacation_request,
    delete_pending_vacation_request,
    reject_vacation_request,
)
from apps.leave.services.schedule_changes import (
    approve_schedule_change_request,
    create_schedule_change_request,
    get_schedule_change_requests_queryset,
    is_manager_initiated_schedule_change,
    reject_schedule_change_request,
)
from apps.leave.services.urgent_closures import (
    accept_urgent_closure_by_employee,
    approve_urgent_closure_by_manager,
    build_urgent_closure_preview,
    can_department_review_urgent_closure,
    can_employee_review_urgent_closure,
    can_finalize_urgent_closure,
    can_view_urgent_closure_request,
    finalize_urgent_closure,
    get_urgent_closure_requests_queryset,
    propose_urgent_closure_period_by_employee,
    reject_urgent_closure,
)
from apps.leave.views.common import (
    _form_errors_to_messages,
    _validation_error_message,
    _parse_preview_date,
    _empty_urgent_closure_preview_payload,
    _urgent_closure_preview_json,
)


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
def urgent_closure_detail(request, pk):
    context = get_user_context(request)
    context = update_context_with_departments(request, context)
    try:
        closure_request = get_urgent_closure_requests_queryset().get(pk=pk)
    except VacationUrgentClosureRequest.DoesNotExist:
        messages.error(request, "Согласование срочного остатка удалено или больше недоступно.")
        return redirect("applications")
    current_employee = get_current_employee(request)
    if not can_view_urgent_closure_request(current_employee, closure_request):
        messages.error(request, "У вас нет прав для просмотра этого согласования.")
        return redirect("main")

    context.update(
        build_urgent_closure_detail_context(
            closure_request,
            current_employee,
            source=request.GET.get("from", ""),
            query_params=request.GET,
        )
    )
    return render(request, "urgent_closure_detail.html", context)


@employee_required
def urgent_closure_employee_preview(request, pk):
    current_employee = get_current_employee(request)
    if request.method != "GET":
        return JsonResponse(
            _empty_urgent_closure_preview_payload("Проверка другого периода доступна только GET-запросом."),
            status=405,
        )

    closure_request = get_object_or_404(get_urgent_closure_requests_queryset(), pk=pk)
    if not can_employee_review_urgent_closure(current_employee, closure_request):
        return JsonResponse(
            _empty_urgent_closure_preview_payload("Проверить другой период может только сотрудник на этапе ответа."),
            status=403,
        )

    try:
        start_date = _parse_preview_date(
            request.GET.get("start_date") or request.GET.get("propose_start_date"),
            "Дата начала",
        )
        end_date = _parse_preview_date(
            request.GET.get("end_date") or request.GET.get("propose_end_date"),
            "Дата окончания",
        )
        preview = build_urgent_closure_preview(
            employee=closure_request.employee,
            planning_year=closure_request.planning_year,
            required_days=closure_request.required_days,
            deadline=closure_request.deadline,
            start_date=start_date,
            end_date=end_date,
        )
    except ValidationError as exc:
        return JsonResponse(_empty_urgent_closure_preview_payload(_validation_error_message(exc)))

    return JsonResponse(_urgent_closure_preview_json(preview))


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
def approve_urgent_closure_manager(request, pk):
    closure_request = get_object_or_404(get_urgent_closure_requests_queryset(), pk=pk)
    current_employee = get_current_employee(request)
    if not can_department_review_urgent_closure(current_employee, closure_request):
        messages.error(request, "Проверить период может только согласующий руководитель.")
        return redirect("urgent_closure_detail", pk=pk)

    if request.method == "POST":
        start_date = end_date = None
        try:
            if request.POST.get("manager_start_date") or request.POST.get("manager_end_date"):
                start_date = _parse_preview_date(request.POST.get("manager_start_date"), "Дата начала")
                end_date = _parse_preview_date(request.POST.get("manager_end_date"), "Дата окончания")
            approve_urgent_closure_by_manager(
                pk,
                reviewer=current_employee,
                comment=request.POST.get("comment", ""),
                start_date=start_date,
                end_date=end_date,
            )
            messages.success(request, "Период проверен и отправлен сотруднику.")
        except ValidationError as exc:
            messages.error(request, _validation_error_message(exc))
    return redirect("urgent_closure_detail", pk=pk)


@employee_required
def accept_urgent_closure_employee(request, pk):
    closure_request = get_object_or_404(get_urgent_closure_requests_queryset(), pk=pk)
    current_employee = get_current_employee(request)
    if not can_employee_review_urgent_closure(current_employee, closure_request):
        messages.error(request, "Принять период может только сотрудник, которому предложен отпуск.")
        return redirect("urgent_closure_detail", pk=pk)

    if request.method == "POST":
        try:
            accept_urgent_closure_by_employee(
                pk,
                employee=current_employee,
                comment=request.POST.get("comment", ""),
            )
            messages.success(request, "Период принят и отправлен HR на финализацию.")
        except ValidationError as exc:
            messages.error(request, _validation_error_message(exc))
    return redirect("urgent_closure_detail", pk=pk)


@employee_required
def propose_urgent_closure_employee(request, pk):
    closure_request = get_object_or_404(get_urgent_closure_requests_queryset(), pk=pk)
    current_employee = get_current_employee(request)
    if not can_employee_review_urgent_closure(current_employee, closure_request):
        messages.error(request, "Предложить другой период может только сотрудник, которому предложен отпуск.")
        return redirect("urgent_closure_detail", pk=pk)

    if request.method == "POST":
        try:
            start_date = _parse_preview_date(request.POST.get("propose_start_date"), "Дата начала")
            end_date = _parse_preview_date(request.POST.get("propose_end_date"), "Дата окончания")
            propose_urgent_closure_period_by_employee(
                pk,
                employee=current_employee,
                start_date=start_date,
                end_date=end_date,
                comment=request.POST.get("comment", ""),
            )
            messages.success(request, "Новый период отправлен руководителю на повторную проверку.")
        except ValidationError as exc:
            messages.error(request, _validation_error_message(exc))
    return redirect("urgent_closure_detail", pk=pk)


@employee_required
def finalize_urgent_closure_hr(request, pk):
    closure_request = get_object_or_404(get_urgent_closure_requests_queryset(), pk=pk)
    current_employee = get_current_employee(request)
    if not can_finalize_urgent_closure(current_employee, closure_request):
        messages.error(request, "Финализировать закрытие срочного остатка может только HR.")
        return redirect("urgent_closure_detail", pk=pk)

    if request.method == "POST":
        try:
            finalize_urgent_closure(pk, actor=current_employee, comment=request.POST.get("comment", ""))
            messages.success(request, "Срочный остаток закрыт: пункт графика создан в предыдущем году.")
        except ValidationError as exc:
            messages.error(request, _validation_error_message(exc))
    return redirect("urgent_closure_detail", pk=pk)


@employee_required
def reject_urgent_closure_request(request, pk):
    closure_request = get_object_or_404(get_urgent_closure_requests_queryset(), pk=pk)
    current_employee = get_current_employee(request)
    if not (
        can_department_review_urgent_closure(current_employee, closure_request)
        or can_employee_review_urgent_closure(current_employee, closure_request)
        or can_finalize_urgent_closure(current_employee, closure_request)
    ):
        messages.error(request, "У вас нет прав для отклонения этого согласования.")
        return redirect("urgent_closure_detail", pk=pk)

    if request.method == "POST":
        try:
            reject_urgent_closure(pk, actor=current_employee, comment=request.POST.get("comment", ""))
            messages.success(request, "Согласование срочного остатка отклонено.")
        except ValidationError as exc:
            messages.error(request, _validation_error_message(exc))
    return redirect("urgent_closure_detail", pk=pk)
