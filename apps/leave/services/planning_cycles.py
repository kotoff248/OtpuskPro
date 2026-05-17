from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.services import is_enterprise_head_employee, is_hr_employee
from apps.leave.models import (
    VacationPlanningCycle,
    VacationPreferenceCollection,
    VacationSchedule,
    VacationUrgentClosureRequest,
)


def fallback_planning_year(today=None):
    today = today or timezone.localdate()
    return today.year + 1


def get_active_planning_cycle():
    return VacationPlanningCycle.objects.filter(status=VacationPlanningCycle.STATUS_ACTIVE).order_by("-year", "-id").first()


def get_active_planning_year(today=None):
    cycle = get_active_planning_cycle()
    if cycle is not None:
        return cycle.year
    return fallback_planning_year(today)


def is_active_planning_year(year):
    return int(year) == get_active_planning_year()


def ensure_active_planning_cycle(year, *, actor=None):
    now = timezone.now()
    with transaction.atomic():
        VacationPlanningCycle.objects.select_for_update().filter(
            status=VacationPlanningCycle.STATUS_ACTIVE
        ).exclude(year=year).update(status=VacationPlanningCycle.STATUS_CLOSED, closed_at=now)
        cycle, created = VacationPlanningCycle.objects.select_for_update().get_or_create(
            year=year,
            defaults={
                "status": VacationPlanningCycle.STATUS_ACTIVE,
                "started_by": actor,
                "started_at": now,
                "closed_at": None,
            },
        )
        if not created and cycle.status != VacationPlanningCycle.STATUS_ACTIVE:
            cycle.status = VacationPlanningCycle.STATUS_ACTIVE
            cycle.started_by = actor or cycle.started_by
            cycle.started_at = now
            cycle.closed_at = None
            cycle.save(update_fields=["status", "started_by", "started_at", "closed_at", "updated_at"])
        elif not created and cycle.closed_at is not None:
            cycle.closed_at = None
            cycle.save(update_fields=["closed_at", "updated_at"])
        return cycle


def available_planning_years(selected_year=None, today=None):
    fallback_year = fallback_planning_year(today)
    active_year = get_active_planning_year(today)
    lower_bound = min(fallback_year, active_year)
    years = set()
    if selected_year:
        years.add(int(selected_year))
    years.add(active_year)
    years.update(VacationPlanningCycle.objects.values_list("year", flat=True))
    years.update(VacationSchedule.objects.filter(year__gte=lower_bound).values_list("year", flat=True))
    years.update(VacationPreferenceCollection.objects.filter(year__gte=lower_bound).values_list("year", flat=True))
    return sorted(years, reverse=True)


def get_next_planning_cycle_start_state(year, actor):
    if not (is_hr_employee(actor) or is_enterprise_head_employee(actor)):
        return {
            "can_start": False,
            "reason": "Начать следующий год планирования может только HR или руководитель предприятия.",
        }
    active_year = get_active_planning_year()
    if int(year) != active_year:
        return {
            "can_start": False,
            "reason": f"Следующий год можно запустить только из активного планирования {active_year} года.",
        }

    schedule = VacationSchedule.objects.filter(year=year).first()
    if schedule is None:
        return {"can_start": False, "reason": "Сначала создайте и утвердите график текущего планового года."}
    if schedule.status != VacationSchedule.STATUS_APPROVED:
        return {"can_start": False, "reason": "Следующий год можно начать только после утверждения текущего графика."}

    next_year = int(year) + 1
    if VacationSchedule.objects.filter(year=next_year).exists() or VacationPreferenceCollection.objects.filter(year=next_year).exists():
        return {"can_start": False, "reason": f"По {next_year} году уже есть данные планирования."}
    if VacationUrgentClosureRequest.objects.filter(planning_year=next_year).exists():
        return {"can_start": False, "reason": f"По {next_year} году уже есть срочные закрытия."}

    return {
        "can_start": True,
        "reason": "",
        "next_year": next_year,
    }


@transaction.atomic
def start_next_planning_cycle(year, actor):
    state = get_next_planning_cycle_start_state(year, actor)
    if not state.get("can_start"):
        raise ValidationError(state.get("reason") or "Нельзя начать следующий год планирования.")

    now = timezone.now()
    current_cycle, _ = VacationPlanningCycle.objects.select_for_update().get_or_create(
        year=year,
        defaults={
            "status": VacationPlanningCycle.STATUS_ACTIVE,
            "started_by": actor,
            "started_at": now,
        },
    )
    current_cycle.status = VacationPlanningCycle.STATUS_CLOSED
    current_cycle.closed_at = now
    current_cycle.save(update_fields=["status", "closed_at", "updated_at"])

    next_cycle = ensure_active_planning_cycle(state["next_year"], actor=actor)
    return {
        "previous_cycle": current_cycle,
        "cycle": next_cycle,
        "year": next_cycle.year,
    }
