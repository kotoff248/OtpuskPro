from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.leave.models import VacationRequest, VacationSchedule, VacationScheduleChangeRequest, VacationScheduleItem

from .dates import get_chargeable_leave_days, normalize_date_value
from .risk import calculate_vacation_request_risk


def _get_prefetched_schedule_change_request(item):
    prefetched = getattr(item, "_prefetched_objects_cache", {}).get("change_requests")
    if prefetched is None:
        return None

    changes = list(prefetched)
    if not changes:
        return None

    approved = [change for change in changes if change.status == VacationScheduleChangeRequest.STATUS_APPROVED]
    candidates = approved or changes
    return max(
        candidates,
        key=lambda change: (
            change.reviewed_at is not None,
            change.reviewed_at or change.created_at,
            change.id,
        ),
    )


def get_schedule_item_detail_reference(item):
    if item.created_from_vacation_request_id:
        return {
            "detail_url": reverse("vacation_detail", args=[item.created_from_vacation_request_id]),
            "detail_label": "Открыть заявку",
        }

    if item.created_from_change_request_id:
        return {
            "detail_url": reverse("schedule_change_detail", args=[item.created_from_change_request_id]),
            "detail_label": "Открыть перенос",
        }

    if item.status == VacationScheduleItem.STATUS_TRANSFERRED:
        change_request = _get_prefetched_schedule_change_request(item)
        if change_request is None:
            changes = VacationScheduleChangeRequest.objects.filter(schedule_item=item)
            change_request = (
                changes.filter(status=VacationScheduleChangeRequest.STATUS_APPROVED)
                .order_by("-reviewed_at", "-created_at", "-id")
                .first()
            )
            if change_request is None:
                change_request = changes.order_by("-created_at", "-id").first()
        if change_request is not None:
            return {
                "detail_url": reverse("schedule_change_detail", args=[change_request.id]),
                "detail_label": "Открыть перенос",
            }

    return {"detail_url": "", "detail_label": ""}


def create_schedule_item_from_paid_vacation_request(vacation, risk_payload=None):
    if vacation.vacation_type != "paid" or vacation.status != VacationRequest.STATUS_APPROVED:
        return None

    existing_item = VacationScheduleItem.objects.filter(
        created_from_vacation_request=vacation,
    ).order_by("id").first()
    if existing_item is not None:
        return existing_item

    start_date = normalize_date_value(vacation.start_date)
    end_date = normalize_date_value(vacation.end_date)
    schedule = VacationSchedule.objects.filter(year=start_date.year).first()
    if schedule is None:
        raise ValidationError("Для года оплачиваемой заявки не найден утверждённый график отпусков.")
    if schedule.status not in {VacationSchedule.STATUS_APPROVED, VacationSchedule.STATUS_ARCHIVED}:
        raise ValidationError("Оплачиваемую заявку можно добавить только в утверждённый график отпусков.")

    if risk_payload is None:
        risk_payload = calculate_vacation_request_risk(
            employee=vacation.employee,
            start_date=start_date,
            end_date=end_date,
            vacation_type=vacation.vacation_type,
            exclude_request_id=vacation.id,
        )

    return VacationScheduleItem.objects.create(
        schedule=schedule,
        employee=vacation.employee,
        start_date=start_date,
        end_date=end_date,
        vacation_type=vacation.vacation_type,
        chargeable_days=get_chargeable_leave_days(start_date, end_date, vacation.vacation_type),
        status=VacationScheduleItem.STATUS_APPROVED,
        source=VacationScheduleItem.SOURCE_MANUAL,
        risk_score=risk_payload["risk_score"],
        risk_level=risk_payload["risk_level"],
        generated_by_ai=False,
        was_changed_by_manager=False,
        manager_comment="Создано после одобрения оплачиваемой заявки вне графика.",
        created_from_vacation_request=vacation,
    )
