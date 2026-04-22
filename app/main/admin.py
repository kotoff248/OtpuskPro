from django.contrib import admin

from .models import Departments, Employees, VacationRequest


admin.site.register(Employees)
admin.site.register(Departments)
admin.site.register(VacationRequest)
