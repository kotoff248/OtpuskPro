from django.utils import timezone

from apps.leave.models import VacationRequest, VacationScheduleItem

from .calendar import build_calendar_base_data, build_calendar_rows
from .constants import RUSSIAN_MONTH_SHORT_NAMES
from .dates import get_month_end, get_month_range, get_overlap_days
from .querysets import exclude_converted_paid_requests

def build_analytics_payload(employee_ids=None):
    today = timezone.localdate()
    year = today.year
    employees, employee_day_status, employee_entries = build_calendar_base_data(year, employee_ids=employee_ids)
    rows, _ = build_calendar_rows(
        employees,
        employee_day_status,
        employee_entries,
        year=year,
        month=today.month,
        view_mode="year",
        today=today,
    )

    vacation_counts = [0] * 12
    average_duration_days = [0] * 12
    planned_days = [0] * 12
    duration_totals = [0] * 12
    for entries in employee_entries.values():
        for entry in entries:
            for month_start in get_month_range(entry["start_date"], entry["end_date"]):
                overlap_days = get_overlap_days(entry["start_date"], entry["end_date"], month_start, get_month_end(month_start))
                month_index = month_start.month - 1
                vacation_counts[month_index] += 1
                duration_totals[month_index] += overlap_days
                planned_days[month_index] += overlap_days

    for month_index, vacations_in_month in enumerate(vacation_counts):
        if vacations_in_month:
            average_duration_days[month_index] = round(duration_totals[month_index] / vacations_in_month, 2)

    total_employees = len(employees)
    employee_id_set = {employee.id for employee in employees}
    approved_absence_requests = VacationRequest.objects.filter(
        employee_id__in=employee_id_set,
        status=VacationRequest.STATUS_APPROVED,
        start_date__lte=today,
        end_date__gte=today,
    )
    approved_absence_requests = exclude_converted_paid_requests(
        approved_absence_requests,
        employee_ids=employee_id_set,
        start_date=today,
        end_date=today,
    )
    absent_employee_ids = set(approved_absence_requests.values_list("employee_id", flat=True))
    absent_employee_ids.update(
        VacationScheduleItem.objects.filter(
            employee_id__in=employee_id_set,
            status__in=VacationScheduleItem.ACTIVE_STATUSES,
            start_date__lte=today,
            end_date__gte=today,
        ).values_list("employee_id", flat=True)
    )
    employees_not_on_vacation_count = total_employees - len(absent_employee_ids)
    working_employees = round((employees_not_on_vacation_count / total_employees) * 100) if total_employees else 0
    total_applications_count = VacationRequest.objects.count() if employee_ids is None else VacationRequest.objects.filter(employee_id__in=employee_ids).count()
    canceled_count = (
        VacationRequest.objects.filter(status=VacationRequest.STATUS_REJECTED).count()
        if employee_ids is None
        else VacationRequest.objects.filter(employee_id__in=employee_ids, status=VacationRequest.STATUS_REJECTED).count()
    )
    rejection_percentage = round((canceled_count / total_applications_count) * 100) if total_applications_count else 0
    avg_vacation_days = round(
        sum(employee.annual_paid_leave_days for employee in employees) / total_employees,
        2,
    ) if total_employees else 0

    return {
        "labels": RUSSIAN_MONTH_SHORT_NAMES,
        "values1": vacation_counts,
        "values2": average_duration_days,
        "values3": planned_days,
        "rows": rows,
        "total_employees": total_employees,
        "employees_not_on_vacation_count": employees_not_on_vacation_count,
        "working_employees": working_employees,
        "total_applications_count": total_applications_count,
        "canceled_count": canceled_count,
        "rejection_percentage": rejection_percentage,
        "avg_vacation_days": avg_vacation_days,
    }
