from django.core.management.base import BaseCommand
from apps.employees.models import Employees
from apps.leave.services import sync_employee_vacation_metrics


class Command(BaseCommand):
    help = "Rebuild employee vacation entitlement ledgers"

    def handle(self, *args, **kwargs):
        employees = Employees.objects.all()

        for employee in employees:
            sync_employee_vacation_metrics(employee)

        self.stdout.write(self.style.SUCCESS("Журнал отпускных дней пересчитан"))
