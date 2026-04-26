from django.contrib import admin

from .models import Departments, Employees


admin.site.register(Employees)
admin.site.register(Departments)

