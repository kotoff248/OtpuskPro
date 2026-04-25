from django.contrib import admin

from .models import (
    DepartmentStaffingRule,
    DepartmentWorkload,
    VacationPreference,
    VacationRequest,
    VacationSchedule,
    VacationScheduleAuthorizedApproval,
    VacationScheduleChangeRequest,
    VacationScheduleDepartmentApproval,
    VacationScheduleEnterpriseApproval,
    VacationScheduleItem,
)


admin.site.register(VacationRequest)
admin.site.register(VacationSchedule)
admin.site.register(VacationScheduleItem)
admin.site.register(VacationScheduleDepartmentApproval)
admin.site.register(VacationScheduleEnterpriseApproval)
admin.site.register(VacationScheduleAuthorizedApproval)
admin.site.register(VacationScheduleChangeRequest)
admin.site.register(VacationPreference)
admin.site.register(DepartmentWorkload)
admin.site.register(DepartmentStaffingRule)
