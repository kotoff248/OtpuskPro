from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.leave.models import VacationRequest
from apps.leave.services import sync_employee_vacation_metrics


@receiver(post_save, sender=VacationRequest)
def update_employee_status(sender, instance, **kwargs):
    sync_employee_vacation_metrics(instance.employee)


@receiver(post_delete, sender=VacationRequest)
def reset_employee_status(sender, instance, **kwargs):
    sync_employee_vacation_metrics(instance.employee)

