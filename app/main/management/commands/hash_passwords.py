from django.core.management.base import BaseCommand
from django.contrib.auth.hashers import make_password
from main.models import Employees

class Command(BaseCommand):
    help = 'Hash all passwords in the Employees table'

    def handle(self, *args, **kwargs):
        employees = Employees.objects.all()
        for employee in employees:
            if not employee.password.startswith('pbkdf2_'):  # Проверка, захэширован ли пароль
                employee.password = make_password(employee.password)
                employee.save()
        self.stdout.write(self.style.SUCCESS('Successfully hashed all passwords'))