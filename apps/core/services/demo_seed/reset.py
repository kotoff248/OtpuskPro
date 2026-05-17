from django.contrib.auth import get_user_model
from django.core.management.color import no_style
from django.db import connection

from apps.core.models import Notification
from apps.employees.models import (
    DepartmentCoverageRule,
    Departments,
    EmployeePosition,
    Employees,
    ProductionGroup,
    ProductionGroupSubstitutionRule,
)
from apps.leave.models import (
    DepartmentStaffingRule,
    DepartmentWorkload,
    VacationEntitlementAllocation,
    VacationEntitlementPeriod,
    VacationPlanningCycle,
    VacationPreference,
    VacationPreferenceCollection,
    VacationRequest,
    VacationRequestHistory,
    VacationSchedule,
    VacationScheduleAuthorizedApproval,
    VacationScheduleCandidate,
    VacationScheduleCandidateFeedback,
    VacationScheduleCandidatePackage,
    VacationScheduleCandidatePackagePeriod,
    VacationScheduleChangeRequest,
    VacationScheduleDepartmentApproval,
    VacationScheduleEnterpriseApproval,
    VacationScheduleGenerationRun,
    VacationScheduleItem,
    VacationUrgentClosureRequest,
)


class DemoSeedResetMixin:
    def _reset_demo_data(self):
        user_ids = list(Employees.objects.exclude(user_id=None).values_list("user_id", flat=True))

        VacationScheduleCandidateFeedback.objects.all().delete()
        VacationScheduleCandidatePackagePeriod.objects.all().delete()
        VacationScheduleCandidatePackage.objects.all().delete()
        VacationScheduleCandidate.objects.all().delete()
        VacationScheduleGenerationRun.objects.all().delete()
        VacationScheduleChangeRequest.objects.all().delete()
        VacationUrgentClosureRequest.objects.all().delete()
        VacationRequestHistory.objects.all().delete()
        VacationEntitlementAllocation.objects.all().delete()
        VacationEntitlementPeriod.objects.all().delete()
        VacationPlanningCycle.objects.all().delete()
        VacationPreferenceCollection.objects.all().delete()
        VacationPreference.objects.all().delete()
        DepartmentWorkload.objects.all().delete()
        DepartmentStaffingRule.objects.all().delete()
        ProductionGroupSubstitutionRule.objects.all().delete()
        DepartmentCoverageRule.objects.all().delete()
        EmployeePosition.objects.all().delete()
        ProductionGroup.objects.all().delete()
        VacationSchedule.objects.all().delete()
        VacationRequest.objects.all().delete()
        Employees.objects.all().delete()
        Departments.objects.all().delete()

        if user_ids:
            get_user_model().objects.filter(id__in=user_ids).delete()

        self._reset_demo_sequences()

    def _reset_demo_sequences(self):
        models = [
            get_user_model(),
            Notification,
            Departments,
            EmployeePosition,
            Employees,
            ProductionGroup,
            ProductionGroupSubstitutionRule,
            DepartmentCoverageRule,
            DepartmentStaffingRule,
            DepartmentWorkload,
            VacationEntitlementAllocation,
            VacationEntitlementPeriod,
            VacationPlanningCycle,
            VacationPreference,
            VacationPreferenceCollection,
            VacationRequest,
            VacationRequestHistory,
            VacationSchedule,
            VacationScheduleAuthorizedApproval,
            VacationScheduleCandidate,
            VacationScheduleCandidateFeedback,
            VacationScheduleCandidatePackage,
            VacationScheduleCandidatePackagePeriod,
            VacationScheduleChangeRequest,
            VacationScheduleDepartmentApproval,
            VacationScheduleEnterpriseApproval,
            VacationScheduleGenerationRun,
            VacationScheduleItem,
            VacationUrgentClosureRequest,
        ]
        sequence_sql = connection.ops.sequence_reset_sql(no_style(), models)
        if not sequence_sql:
            return
        with connection.cursor() as cursor:
            for sql in sequence_sql:
                cursor.execute(sql)
