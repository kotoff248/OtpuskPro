from django.contrib import admin

from .models import (
    DepartmentCoverageRule,
    Departments,
    EmployeePosition,
    Employees,
    ProductionGroup,
    ProductionGroupSubstitutionRule,
)


admin.site.register(Employees)
admin.site.register(Departments)
admin.site.register(ProductionGroup)
admin.site.register(EmployeePosition)
admin.site.register(DepartmentCoverageRule)
admin.site.register(ProductionGroupSubstitutionRule)

