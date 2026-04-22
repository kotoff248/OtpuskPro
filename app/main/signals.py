from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import VacationRequest


def sync_employee_work_status(employee):
    today = timezone.now().date()
    has_active_vacation = VacationRequest.objects.filter(
        employee=employee,
        status=VacationRequest.STATUS_APPROVED,
        start_date__lte=today,
        end_date__gte=today,
    ).exists()
    employee.is_working = not has_active_vacation
    employee.save(update_fields=['is_working'])


@receiver(post_save, sender=VacationRequest)
def update_employee_status(sender, instance, **kwargs):
    sync_employee_work_status(instance.employee)


@receiver(post_delete, sender=VacationRequest)
def reset_employee_status(sender, instance, **kwargs):
    sync_employee_work_status(instance.employee)
