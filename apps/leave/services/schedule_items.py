from django.core.exceptions import ValidationError

from apps.leave.models import VacationRequest, VacationSchedule, VacationScheduleItem

from .dates import get_chargeable_leave_days, normalize_date_value
from .risk import calculate_vacation_request_risk

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
