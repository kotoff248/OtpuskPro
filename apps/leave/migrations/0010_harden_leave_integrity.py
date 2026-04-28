from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField, RangeBoundary, RangeOperators
from django.contrib.postgres.operations import BtreeGistExtension
from django.db import migrations, models
from django.db.models import Count, F, Func
from django.db.models.functions import Greatest, Least


ACTIVE_REQUEST_STATUSES = ("pending", "approved")
ACTIVE_SCHEDULE_STATUSES = ("planned", "approved")


def _ranges_overlap(left_start, left_end, right_start, right_end):
    return left_start <= right_end and right_start <= left_end


def _find_overlaps(rows):
    conflicts = []
    for index, left in enumerate(rows):
        for right in rows[index + 1:]:
            if _ranges_overlap(left["start_date"], left["end_date"], right["start_date"], right["end_date"]):
                conflicts.append((left["id"], right["id"]))
    return conflicts


def validate_existing_leave_data(apps, schema_editor):
    VacationRequest = apps.get_model("leave", "VacationRequest")
    VacationScheduleItem = apps.get_model("leave", "VacationScheduleItem")
    VacationEntitlementPeriod = apps.get_model("leave", "VacationEntitlementPeriod")
    VacationEntitlementAllocation = apps.get_model("leave", "VacationEntitlementAllocation")
    VacationScheduleChangeRequest = apps.get_model("leave", "VacationScheduleChangeRequest")
    VacationPreference = apps.get_model("leave", "VacationPreference")
    DepartmentWorkload = apps.get_model("leave", "DepartmentWorkload")
    DepartmentStaffingRule = apps.get_model("leave", "DepartmentStaffingRule")

    errors = []

    def add_bad_date_errors(label, queryset, start_field, end_field):
        bad_ids = list(
            queryset.filter(**{f"{start_field}__gt": F(end_field)}).values_list("id", flat=True)[:20]
        )
        if bad_ids:
            errors.append(f"{label}: start/end conflict ids={bad_ids}")

    add_bad_date_errors("VacationRequest", VacationRequest.objects, "start_date", "end_date")
    add_bad_date_errors("VacationScheduleItem", VacationScheduleItem.objects, "start_date", "end_date")
    add_bad_date_errors("VacationEntitlementPeriod", VacationEntitlementPeriod.objects, "period_start", "period_end")
    add_bad_date_errors("VacationScheduleChangeRequest.old", VacationScheduleChangeRequest.objects, "old_start_date", "old_end_date")
    add_bad_date_errors("VacationScheduleChangeRequest.new", VacationScheduleChangeRequest.objects, "new_start_date", "new_end_date")

    bad_preferences = list(
        VacationPreference.objects.filter(
            models.Q(start_date__isnull=True, end_date__isnull=False)
            | models.Q(start_date__isnull=False, end_date__isnull=True)
            | models.Q(start_date__gt=F("end_date"))
        ).values_list("id", flat=True)[:20]
    )
    if bad_preferences:
        errors.append(f"VacationPreference: invalid date range ids={bad_preferences}")

    bad_workload_months = list(
        DepartmentWorkload.objects.filter(models.Q(month__lt=1) | models.Q(month__gt=12)).values_list("id", flat=True)[:20]
    )
    if bad_workload_months:
        errors.append(f"DepartmentWorkload: invalid month ids={bad_workload_months}")

    bad_workload_levels = list(
        DepartmentWorkload.objects.filter(models.Q(load_level__lt=1) | models.Q(load_level__gt=5)).values_list("id", flat=True)[:20]
    )
    if bad_workload_levels:
        errors.append(f"DepartmentWorkload: invalid load_level ids={bad_workload_levels}")

    bad_change_load_levels = list(
        VacationScheduleChangeRequest.objects.filter(
            models.Q(department_load_level__lt=1) | models.Q(department_load_level__gt=5)
        ).values_list("id", flat=True)[:20]
    )
    if bad_change_load_levels:
        errors.append(f"VacationScheduleChangeRequest: invalid department_load_level ids={bad_change_load_levels}")

    bad_request_load_levels = list(
        VacationRequest.objects.filter(
            models.Q(department_load_level__lt=1) | models.Q(department_load_level__gt=5)
        ).values_list("id", flat=True)[:20]
    )
    if bad_request_load_levels:
        errors.append(f"VacationRequest: invalid department_load_level ids={bad_request_load_levels}")

    bad_criticality = list(
        DepartmentStaffingRule.objects.filter(
            models.Q(criticality_level__lt=1) | models.Q(criticality_level__gt=5)
        ).values_list("id", flat=True)[:20]
    )
    if bad_criticality:
        errors.append(f"DepartmentStaffingRule: invalid criticality_level ids={bad_criticality}")

    bad_allocations = list(
        VacationEntitlementAllocation.objects.filter(allocated_days__lte=0).values_list("id", flat=True)[:20]
    )
    if bad_allocations:
        errors.append(f"VacationEntitlementAllocation: non-positive allocated_days ids={bad_allocations}")

    duplicate_change_sources = list(
        VacationScheduleItem.objects.filter(created_from_change_request__isnull=False)
        .values("created_from_change_request_id")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
        .values_list("created_from_change_request_id", flat=True)[:20]
    )
    if duplicate_change_sources:
        errors.append(f"VacationScheduleItem: duplicate change request sources={duplicate_change_sources}")

    duplicate_request_sources = list(
        VacationScheduleItem.objects.filter(created_from_vacation_request__isnull=False)
        .values("created_from_vacation_request_id")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
        .values_list("created_from_vacation_request_id", flat=True)[:20]
    )
    if duplicate_request_sources:
        errors.append(f"VacationScheduleItem: duplicate vacation request sources={duplicate_request_sources}")

    active_request_employee_ids = (
        VacationRequest.objects.filter(status__in=ACTIVE_REQUEST_STATUSES)
        .values_list("employee_id", flat=True)
        .distinct()
    )
    for employee_id in active_request_employee_ids:
        rows = list(
            VacationRequest.objects.filter(employee_id=employee_id, status__in=ACTIVE_REQUEST_STATUSES)
            .order_by("start_date", "end_date", "id")
            .values("id", "start_date", "end_date")
        )
        conflicts = _find_overlaps(rows)
        if conflicts:
            errors.append(f"VacationRequest: employee={employee_id} overlapping ids={conflicts[:5]}")

    active_schedule_employee_ids = (
        VacationScheduleItem.objects.filter(status__in=ACTIVE_SCHEDULE_STATUSES)
        .values_list("employee_id", flat=True)
        .distinct()
    )
    for employee_id in active_schedule_employee_ids:
        rows = list(
            VacationScheduleItem.objects.filter(employee_id=employee_id, status__in=ACTIVE_SCHEDULE_STATUSES)
            .order_by("start_date", "end_date", "id")
            .values("id", "start_date", "end_date")
        )
        conflicts = _find_overlaps(rows)
        if conflicts:
            errors.append(f"VacationScheduleItem: employee={employee_id} overlapping ids={conflicts[:5]}")

    employee_ids = set(active_request_employee_ids) | set(active_schedule_employee_ids)
    for employee_id in employee_ids:
        requests = list(
            VacationRequest.objects.filter(employee_id=employee_id, status__in=ACTIVE_REQUEST_STATUSES)
            .order_by("start_date", "end_date", "id")
            .values("id", "start_date", "end_date", "status", "vacation_type")
        )
        schedule_items = list(
            VacationScheduleItem.objects.filter(employee_id=employee_id, status__in=ACTIVE_SCHEDULE_STATUSES)
            .order_by("start_date", "end_date", "id")
            .values("id", "start_date", "end_date", "created_from_vacation_request_id")
        )
        conflicts = []
        for request_obj in requests:
            for schedule_item in schedule_items:
                if not _ranges_overlap(
                    request_obj["start_date"],
                    request_obj["end_date"],
                    schedule_item["start_date"],
                    schedule_item["end_date"],
                ):
                    continue
                linked_paid_request = (
                    request_obj["status"] == "approved"
                    and request_obj["vacation_type"] == "paid"
                    and schedule_item["created_from_vacation_request_id"] == request_obj["id"]
                )
                if not linked_paid_request:
                    conflicts.append((request_obj["id"], schedule_item["id"]))
        if conflicts:
            errors.append(f"Request/Schedule: employee={employee_id} overlapping ids={conflicts[:5]}")

    if errors:
        raise RuntimeError(
            "Cannot add leave integrity constraints while existing data has conflicts:\n"
            + "\n".join(errors[:30])
        )


REQUEST_SCHEDULE_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION leave_validate_request_schedule_overlap()
RETURNS trigger AS $$
BEGIN
    IF NEW.start_date > NEW.end_date THEN
        RETURN NEW;
    END IF;

    IF NEW.status IN ('pending', 'approved') THEN
        IF EXISTS (
            SELECT 1
            FROM leave_vacationscheduleitem item
            WHERE item.employee_id = NEW.employee_id
              AND item.status IN ('planned', 'approved')
              AND daterange(item.start_date, item.end_date, '[]') && daterange(NEW.start_date, NEW.end_date, '[]')
              AND NOT (
                  NEW.status = 'approved'
                  AND NEW.vacation_type = 'paid'
                  AND item.created_from_vacation_request_id = NEW.id
              )
        ) THEN
            RAISE EXCEPTION
                'Active vacation request % overlaps active schedule item for employee %',
                NEW.id,
                NEW.employee_id
                USING ERRCODE = '23P01';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION leave_validate_schedule_request_overlap()
RETURNS trigger AS $$
BEGIN
    IF NEW.start_date > NEW.end_date THEN
        RETURN NEW;
    END IF;

    IF NEW.status IN ('planned', 'approved') THEN
        IF EXISTS (
            SELECT 1
            FROM leave_vacationrequest request
            WHERE request.employee_id = NEW.employee_id
              AND request.status IN ('pending', 'approved')
              AND daterange(request.start_date, request.end_date, '[]') && daterange(NEW.start_date, NEW.end_date, '[]')
              AND NOT (
                  request.status = 'approved'
                  AND request.vacation_type = 'paid'
                  AND NEW.created_from_vacation_request_id = request.id
              )
        ) THEN
            RAISE EXCEPTION
                'Active schedule item % overlaps active vacation request for employee %',
                NEW.id,
                NEW.employee_id
                USING ERRCODE = '23P01';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS leave_vacationrequest_overlap_guard ON leave_vacationrequest;
CREATE TRIGGER leave_vacationrequest_overlap_guard
BEFORE INSERT OR UPDATE OF employee_id, start_date, end_date, status, vacation_type
ON leave_vacationrequest
FOR EACH ROW
EXECUTE FUNCTION leave_validate_request_schedule_overlap();

DROP TRIGGER IF EXISTS leave_vacationscheduleitem_overlap_guard ON leave_vacationscheduleitem;
CREATE TRIGGER leave_vacationscheduleitem_overlap_guard
BEFORE INSERT OR UPDATE OF employee_id, start_date, end_date, status, created_from_vacation_request_id
ON leave_vacationscheduleitem
FOR EACH ROW
EXECUTE FUNCTION leave_validate_schedule_request_overlap();
"""


REQUEST_SCHEDULE_TRIGGER_REVERSE_SQL = """
DROP TRIGGER IF EXISTS leave_vacationrequest_overlap_guard ON leave_vacationrequest;
DROP TRIGGER IF EXISTS leave_vacationscheduleitem_overlap_guard ON leave_vacationscheduleitem;
DROP FUNCTION IF EXISTS leave_validate_request_schedule_overlap();
DROP FUNCTION IF EXISTS leave_validate_schedule_request_overlap();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("leave", "0009_convert_approved_paid_requests_to_schedule_items"),
    ]

    operations = [
        BtreeGistExtension(),
        migrations.RunPython(validate_existing_leave_data, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="vacationrequest",
            constraint=models.CheckConstraint(
                check=models.Q(start_date__lte=F("end_date")),
                name="vacation_request_start_before_end",
            ),
        ),
        migrations.AddConstraint(
            model_name="vacationrequest",
            constraint=models.CheckConstraint(
                check=models.Q(department_load_level__gte=1, department_load_level__lte=5),
                name="vacation_request_department_load_1_5",
            ),
        ),
        migrations.AddConstraint(
            model_name="vacationrequest",
            constraint=ExclusionConstraint(
                name="exclude_overlapping_active_vacation_requests",
                expressions=[
                    ("employee", RangeOperators.EQUAL),
                    (
                        Func(
                            Least("start_date", "end_date"),
                            Greatest("start_date", "end_date"),
                            RangeBoundary(inclusive_lower=True, inclusive_upper=True),
                            function="DATERANGE",
                            output_field=DateRangeField(),
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                ],
                condition=models.Q(status__in=ACTIVE_REQUEST_STATUSES),
            ),
        ),
        migrations.AddConstraint(
            model_name="vacationscheduleitem",
            constraint=models.CheckConstraint(
                check=models.Q(start_date__lte=F("end_date")),
                name="schedule_item_start_before_end",
            ),
        ),
        migrations.AddConstraint(
            model_name="vacationscheduleitem",
            constraint=models.UniqueConstraint(
                fields=["created_from_change_request"],
                condition=models.Q(created_from_change_request__isnull=False),
                name="unique_schedule_item_change_request_source",
            ),
        ),
        migrations.AddConstraint(
            model_name="vacationscheduleitem",
            constraint=models.UniqueConstraint(
                fields=["created_from_vacation_request"],
                condition=models.Q(created_from_vacation_request__isnull=False),
                name="unique_schedule_item_vacation_request_source",
            ),
        ),
        migrations.AddConstraint(
            model_name="vacationscheduleitem",
            constraint=ExclusionConstraint(
                name="exclude_overlapping_active_schedule_items",
                expressions=[
                    ("employee", RangeOperators.EQUAL),
                    (
                        Func(
                            Least("start_date", "end_date"),
                            Greatest("start_date", "end_date"),
                            RangeBoundary(inclusive_lower=True, inclusive_upper=True),
                            function="DATERANGE",
                            output_field=DateRangeField(),
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                ],
                condition=models.Q(status__in=ACTIVE_SCHEDULE_STATUSES),
            ),
        ),
        migrations.AddConstraint(
            model_name="vacationentitlementperiod",
            constraint=models.CheckConstraint(
                check=models.Q(period_start__lte=F("period_end")),
                name="entitlement_period_start_before_end",
            ),
        ),
        migrations.AddConstraint(
            model_name="vacationentitlementperiod",
            constraint=models.CheckConstraint(
                check=models.Q(available_from__lte=F("must_use_by")),
                name="entitlement_period_available_before_deadline",
            ),
        ),
        migrations.AddConstraint(
            model_name="vacationentitlementperiod",
            constraint=models.CheckConstraint(
                check=models.Q(entitled_days__gte=0),
                name="entitlement_period_non_negative_days",
            ),
        ),
        migrations.AddConstraint(
            model_name="vacationentitlementallocation",
            constraint=models.CheckConstraint(
                check=models.Q(allocated_days__gt=0),
                name="entitlement_allocation_positive_days",
            ),
        ),
        migrations.AddConstraint(
            model_name="vacationschedulechangerequest",
            constraint=models.CheckConstraint(
                check=models.Q(old_start_date__lte=F("old_end_date")),
                name="schedule_change_old_start_before_end",
            ),
        ),
        migrations.AddConstraint(
            model_name="vacationschedulechangerequest",
            constraint=models.CheckConstraint(
                check=models.Q(new_start_date__lte=F("new_end_date")),
                name="schedule_change_new_start_before_end",
            ),
        ),
        migrations.AddConstraint(
            model_name="vacationschedulechangerequest",
            constraint=models.CheckConstraint(
                check=models.Q(department_load_level__gte=1, department_load_level__lte=5),
                name="schedule_change_department_load_1_5",
            ),
        ),
        migrations.AddConstraint(
            model_name="vacationpreference",
            constraint=models.CheckConstraint(
                check=(
                    models.Q(start_date__isnull=True, end_date__isnull=True)
                    | models.Q(start_date__isnull=False, end_date__isnull=False, start_date__lte=F("end_date"))
                ),
                name="vacation_preference_date_range_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="departmentworkload",
            constraint=models.CheckConstraint(
                check=models.Q(month__gte=1, month__lte=12),
                name="department_workload_month_1_12",
            ),
        ),
        migrations.AddConstraint(
            model_name="departmentworkload",
            constraint=models.CheckConstraint(
                check=models.Q(load_level__gte=1, load_level__lte=5),
                name="department_workload_level_1_5",
            ),
        ),
        migrations.AddConstraint(
            model_name="departmentstaffingrule",
            constraint=models.CheckConstraint(
                check=models.Q(criticality_level__gte=1, criticality_level__lte=5),
                name="department_staffing_criticality_1_5",
            ),
        ),
        migrations.RunSQL(REQUEST_SCHEDULE_TRIGGER_SQL, REQUEST_SCHEDULE_TRIGGER_REVERSE_SQL),
    ]
