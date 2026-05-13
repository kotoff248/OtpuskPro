from datetime import date

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.leave.models import VacationRequest, VacationSchedule, VacationScheduleChangeRequest, VacationScheduleItem

from .constants import ACTIVE_REQUEST_STATUSES, LEAVE_ADVANCE_MONTHS
from .dates import add_months_safe, get_chargeable_leave_days, get_vacation_day_cost, normalize_date_value
from .ledger import get_employee_available_balance
from .querysets import exclude_converted_paid_requests

MIN_CONTINUOUS_PAID_LEAVE_DAYS = 14


def _get_schedule_approval_cutoff(schedule):
    if schedule and schedule.approved_at:
        return timezone.localtime(schedule.approved_at).date()
    if schedule:
        return date(schedule.year - 1, 12, 31)
    return None

def get_paid_request_eligibility_for_year(employee, year, as_of_date=None):
    if employee is None or employee.is_service_account or not employee.is_active_employee:
        return False, "Оплачиваемый отпуск недоступен для служебной или архивной учетной записи."

    schedule = VacationSchedule.objects.filter(year=year).first()
    if schedule is None:
        return False, "Годовой график за выбранный год ещё не утверждён."
    if schedule.status not in {VacationSchedule.STATUS_APPROVED, VacationSchedule.STATUS_ARCHIVED}:
        return False, "Оплачиваемый отпуск доступен только после утверждения годового графика."

    balance_check_date = normalize_date_value(as_of_date or timezone.localdate())
    available_from = add_months_safe(employee.date_joined, LEAVE_ADVANCE_MONTHS)
    if balance_check_date < available_from:
        return False, "Оплачиваемый отпуск доступен после шести месяцев работы."

    available_balance = get_employee_available_balance(employee, as_of_date=balance_check_date)
    if available_balance > 0:
        return True, "Можно запросить оплачиваемый отпуск из свободного остатка. Заявка пройдёт проверку баланса, пересечений и нагрузки отдела."

    approval_cutoff = _get_schedule_approval_cutoff(schedule)
    if approval_cutoff is None or employee.date_joined <= approval_cutoff:
        return False, "Свободного оплачиваемого остатка нет. Изменение уже запланированного отпуска оформляется через перенос графика."

    has_schedule_item = VacationScheduleItem.objects.filter(
        employee=employee,
        schedule__year=year,
        status__in=VacationScheduleItem.ACTIVE_STATUSES,
    ).exists()
    if has_schedule_item:
        return False, "У сотрудника нет свободного оплачиваемого остатка; отпуск уже занят годовым графиком."

    return True, "Оплачиваемый отпуск вне графика доступен новичку, принятому после утверждения графика."

def get_paid_exception_eligibility_for_year(employee, year):
    return get_paid_request_eligibility_for_year(employee, year)

def validate_paid_exception_request(employee, start_date, end_date):
    if start_date.year != end_date.year:
        raise ValidationError("Оплачиваемая заявка должна быть в пределах одного календарного года.")

    is_allowed, reason = get_paid_request_eligibility_for_year(employee, start_date.year, as_of_date=start_date)
    if not is_allowed:
        raise ValidationError(reason)

    available_from = add_months_safe(employee.date_joined, LEAVE_ADVANCE_MONTHS)
    if start_date < available_from:
        raise ValidationError("Оплачиваемый отпуск доступен после шести месяцев работы.")

def get_overlapping_requests(employee, start_date, end_date, exclude_request_id=None, statuses=None):
    if statuses is None:
        statuses = ACTIVE_REQUEST_STATUSES

    queryset = VacationRequest.objects.filter(
        employee=employee,
        status__in=statuses,
        start_date__lte=end_date,
        end_date__gte=start_date,
    )
    if exclude_request_id is not None:
        queryset = queryset.exclude(pk=exclude_request_id)
    queryset = exclude_converted_paid_requests(
        queryset,
        employee_ids=[employee.id],
        start_date=start_date,
        end_date=end_date,
    )
    return queryset

def get_overlapping_schedule_items(employee, start_date, end_date, statuses=None):
    if statuses is None:
        statuses = VacationScheduleItem.ACTIVE_STATUSES

    return VacationScheduleItem.objects.filter(
        employee=employee,
        status__in=statuses,
        start_date__lte=end_date,
        end_date__gte=start_date,
    )

def _has_required_continuous_paid_leave_part_after_transfer(schedule_item, new_chargeable_days):
    if schedule_item.vacation_type != "paid":
        return True
    if new_chargeable_days >= MIN_CONTINUOUS_PAID_LEAVE_DAYS:
        return True
    return VacationScheduleItem.objects.filter(
        employee=schedule_item.employee,
        schedule=schedule_item.schedule,
        vacation_type="paid",
        status__in=VacationScheduleItem.ACTIVE_STATUSES,
        chargeable_days__gte=MIN_CONTINUOUS_PAID_LEAVE_DAYS,
    ).exclude(pk=schedule_item.pk).exists()

def validate_vacation_request_for_employee(
    employee,
    start_date,
    end_date,
    vacation_type,
    exclude_request_id=None,
    exclude_schedule_item_id=None,
):
    if end_date < start_date:
        raise ValidationError("Дата окончания не может быть раньше даты начала.")

    overlaps_existing = get_overlapping_requests(
        employee=employee,
        start_date=start_date,
        end_date=end_date,
        exclude_request_id=exclude_request_id,
    ).exists()
    if overlaps_existing:
        raise ValidationError("На выбранные даты уже есть активная заявка или одобренный отпуск.")

    overlaps_schedule = get_overlapping_schedule_items(
        employee=employee,
        start_date=start_date,
        end_date=end_date,
    ).exists()
    if exclude_schedule_item_id is not None:
        overlaps_schedule = get_overlapping_schedule_items(
            employee=employee,
            start_date=start_date,
            end_date=end_date,
        ).exclude(pk=exclude_schedule_item_id).exists()
    if overlaps_schedule:
        raise ValidationError("На выбранные даты уже есть отпуск в годовом графике.")

    if vacation_type == "paid" and exclude_schedule_item_id is None:
        validate_paid_exception_request(employee, start_date, end_date)

    requested_cost = get_vacation_day_cost(vacation_type, start_date, end_date)
    if requested_cost > get_employee_available_balance(
        employee,
        as_of_date=start_date,
        exclude_request_id=exclude_request_id,
        exclude_schedule_item_id=exclude_schedule_item_id,
    ):
        raise ValidationError("Выбранный отпуск превышает доступный баланс дней.")

def validate_schedule_change_request(schedule_item, new_start_date, new_end_date, exclude_change_request_id=None):
    today = timezone.localdate()
    if schedule_item.status not in VacationScheduleItem.ACTIVE_STATUSES:
        raise ValidationError("Переносить можно только активный пункт годового графика.")
    if schedule_item.start_date <= today:
        raise ValidationError("Перенос доступен только для будущего отпуска.")
    if new_end_date < new_start_date:
        raise ValidationError("Дата окончания не может быть раньше даты начала.")
    if new_start_date.year != schedule_item.schedule.year or new_end_date.year != schedule_item.schedule.year:
        raise ValidationError("Перенос должен оставаться в пределах года утверждённого графика.")
    pending_changes = VacationScheduleChangeRequest.objects.filter(
        schedule_item=schedule_item,
        status=VacationScheduleChangeRequest.STATUS_PENDING,
    )
    if exclude_change_request_id is not None:
        pending_changes = pending_changes.exclude(pk=exclude_change_request_id)
    if pending_changes.exists():
        raise ValidationError("По этому отпуску уже есть запрос переноса в ожидании.")

    new_chargeable_days = get_chargeable_leave_days(new_start_date, new_end_date, schedule_item.vacation_type)
    if not _has_required_continuous_paid_leave_part_after_transfer(schedule_item, new_chargeable_days):
        raise ValidationError(
            "После переноса в графике не останется оплачиваемой части отпуска не меньше 14 дней."
        )

    validate_vacation_request_for_employee(
        schedule_item.employee,
        new_start_date,
        new_end_date,
        schedule_item.vacation_type,
        exclude_schedule_item_id=schedule_item.id,
    )
    return new_chargeable_days
