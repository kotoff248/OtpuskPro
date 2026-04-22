import datetime

from django.core.management.base import BaseCommand

from main.models import Employees, VacationRequest


class Command(BaseCommand):
    help = 'Update employee status based on approved vacations'

    def handle(self, *args, **kwargs):
        today = datetime.date.today()
        employees = Employees.objects.all()

        for employee in employees:
            has_active_vacation = VacationRequest.objects.filter(
                employee=employee,
                status=VacationRequest.STATUS_APPROVED,
                start_date__lte=today,
                end_date__gte=today,
            ).exists()
            employee.is_working = not has_active_vacation
            employee.save(update_fields=['is_working'])

        self.stdout.write(self.style.SUCCESS('Проверка статуса выполнена'))
