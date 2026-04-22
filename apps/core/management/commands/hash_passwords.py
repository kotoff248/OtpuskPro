from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand

from apps.employees.models import Employees


class Command(BaseCommand):
    help = "Hash all passwords in the Employees table"

    def handle(self, *args, **kwargs):
        employees = Employees.objects.all()
        for employee in employees:
            if not employee.password.startswith("pbkdf2_"):
                employee.password = make_password(employee.password)
                employee.save()
        self.stdout.write(self.style.SUCCESS("Successfully hashed all passwords"))
