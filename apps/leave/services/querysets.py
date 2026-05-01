from apps.leave.models import VacationRequest, VacationScheduleItem

def get_vacation_requests_queryset():
    return VacationRequest.objects.select_related(
        "employee",
        "employee__department",
        "employee__employee_position",
        "employee__employee_position__production_group",
    )

def get_converted_paid_request_ids_queryset(employee_ids=None, start_date=None, end_date=None):
    queryset = VacationScheduleItem.objects.filter(
        created_from_vacation_request__isnull=False,
    )
    if employee_ids is not None:
        queryset = queryset.filter(employee_id__in=employee_ids)
    if start_date is not None:
        queryset = queryset.filter(end_date__gte=start_date)
    if end_date is not None:
        queryset = queryset.filter(start_date__lte=end_date)
    return queryset.values_list("created_from_vacation_request_id", flat=True)

def exclude_converted_paid_requests(queryset, employee_ids=None, start_date=None, end_date=None):
    converted_request_ids = get_converted_paid_request_ids_queryset(
        employee_ids=employee_ids,
        start_date=start_date,
        end_date=end_date,
    )
    return queryset.exclude(
        vacation_type="paid",
        status=VacationRequest.STATUS_APPROVED,
        id__in=converted_request_ids,
    )
