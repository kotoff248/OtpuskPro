from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.test import TestCase
from django.utils import timezone

from apps.accounts.services import sync_employee_user
from apps.employees.models import Departments, EmployeePosition, Employees, ProductionGroup


class LeaveTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.engineering = Departments.objects.create(name="Engineering")
        cls.hr_department = Departments.objects.create(name="HR")
        cls.engineering_group = ProductionGroup.objects.create(department=cls.engineering, name="Инженеры")
        cls.engineering_leadership_group = ProductionGroup.objects.create(department=cls.engineering, name="Руководство отдела")
        cls.hr_group = ProductionGroup.objects.create(department=cls.hr_department, name="HR и офис")
        cls.engineering_position = EmployeePosition.objects.create(
            department=cls.engineering,
            production_group=cls.engineering_group,
            title="Специалист",
        )
        cls.engineering_engineer_position = EmployeePosition.objects.create(
            department=cls.engineering,
            production_group=cls.engineering_group,
            title="Инженер",
        )
        cls.engineering_head_position = EmployeePosition.objects.create(
            department=cls.engineering,
            production_group=cls.engineering_leadership_group,
            title="Руководитель отдела",
        )
        cls.hr_position = EmployeePosition.objects.create(
            department=cls.hr_department,
            production_group=cls.hr_group,
            title="HR",
        )
        cls.enterprise_position = EmployeePosition.objects.create(
            department=cls.hr_department,
            production_group=cls.hr_group,
            title="Директор",
        )
        cls.hr_head_position = EmployeePosition.objects.create(
            department=cls.hr_department,
            production_group=cls.hr_group,
            title="Руководитель отдела",
        )
        cls.outsider_position = EmployeePosition.objects.create(
            department=cls.hr_department,
            production_group=cls.hr_group,
            title="Аналитик",
        )

        cls.employee = Employees.objects.create(
            last_name="Календарев",
            first_name="Иван",
            middle_name="Петрович",
            login="calendar-user",
            position="Специалист",
            employee_position=cls.engineering_position,
            department=cls.engineering,
            date_joined=cls.today - timedelta(days=420),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        sync_employee_user(cls.employee, raw_password="employee-pass")

        cls.department_head = Employees.objects.create(
            last_name="Планова",
            first_name="Мария",
            middle_name="Игоревна",
            login="calendar-dept-head",
            position="Руководитель отдела",
            employee_position=cls.engineering_head_position,
            department=cls.engineering,
            date_joined=cls.today - timedelta(days=800),
            annual_paid_leave_days=52,
            role=Employees.ROLE_DEPARTMENT_HEAD,
        )
        sync_employee_user(cls.department_head, raw_password="dept-head-pass")

        cls.enterprise_head = Employees.objects.create(
            last_name="Директоров",
            first_name="Олег",
            middle_name="Игоревич",
            login="calendar-enterprise-head",
            position="Директор",
            employee_position=cls.enterprise_position,
            department=cls.hr_department,
            date_joined=cls.today - timedelta(days=900),
            annual_paid_leave_days=52,
            role=Employees.ROLE_ENTERPRISE_HEAD,
        )
        sync_employee_user(cls.enterprise_head, raw_password="enterprise-pass")

        cls.hr_employee = Employees.objects.create(
            last_name="Кадрова",
            first_name="Анна",
            middle_name="Сергеевна",
            login="calendar-hr",
            position="HR",
            employee_position=cls.hr_position,
            department=cls.hr_department,
            date_joined=cls.today - timedelta(days=700),
            annual_paid_leave_days=52,
            role=Employees.ROLE_HR,
        )
        sync_employee_user(cls.hr_employee, raw_password="hr-pass")

        cls.authorized_person = Employees.objects.create(
            last_name="Админова",
            first_name="Инна",
            middle_name="Олеговна",
            login="authorized-person",
            position="Уполномоченное лицо",
            date_joined=cls.today - timedelta(days=1000),
            annual_paid_leave_days=52,
            role=Employees.ROLE_AUTHORIZED_PERSON,
        )
        sync_employee_user(cls.authorized_person, raw_password="authorized-pass")

        cls.outsider = Employees.objects.create(
            last_name="Чужой",
            first_name="Петр",
            middle_name="Сергеевич",
            login="other-department-user",
            position="Аналитик",
            employee_position=cls.outsider_position,
            department=cls.hr_department,
            date_joined=cls.today - timedelta(days=300),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        sync_employee_user(cls.outsider, raw_password="outsider-pass")

        cls.foreign_department_head = Employees.objects.create(
            last_name="Другой",
            first_name="Роман",
            middle_name="Олегович",
            login="foreign-department-head",
            position="Руководитель отдела",
            employee_position=cls.hr_head_position,
            department=cls.hr_department,
            date_joined=cls.today - timedelta(days=850),
            annual_paid_leave_days=52,
            role=Employees.ROLE_DEPARTMENT_HEAD,
        )
        sync_employee_user(cls.foreign_department_head, raw_password="foreign-head-pass")

    def _year(self):
        return timezone.localdate().year + 1

    def _deadline(self):
        return timezone.localdate() + timedelta(days=14)

    def _sidebar_link_html(self, response, key):
        html = response.content.decode("utf-8")
        marker = f'data-sidebar-key="{key}"'
        marker_index = html.index(marker)
        link_start = html.rfind("<a", 0, marker_index)
        link_end = html.find(">", marker_index)
        return html[link_start : link_end + 1]

    def _start_collection(self, *, demo_autofill=False):
        self.client.force_login(self.hr_employee.user)
        payload = {
            "year": self._year(),
            "deadline": self._deadline().isoformat(),
        }
        if demo_autofill:
            payload["demo_autofill"] = "on"
        return self.client.post(reverse("preferences_collection_start"), payload)

    def finish_preference_collection(self, year=None):
        from apps.leave.models import VacationPreferenceCollection

        year = year or self._year()
        collection, _ = VacationPreferenceCollection.objects.update_or_create(
            year=year,
            defaults={
                "status": VacationPreferenceCollection.STATUS_FINISHED,
                "deadline": self._deadline(),
                "started_by": self.hr_employee,
                "started_at": timezone.now(),
                "finished_by": self.hr_employee,
                "finished_at": timezone.now(),
            },
        )
        return collection

    def _set_filled_preferences(
        self,
        employee,
        *,
        primary_start,
        primary_end,
        backup_start,
        backup_end,
        comment="",
        remainder_policy=None,
    ):
        from apps.leave.models import VacationPreference

        year = self._year()
        if remainder_policy is None:
            remainder_policy = VacationPreference.REMAINDER_AUTO
        VacationPreference.objects.filter(employee=employee, year=year).delete()
        VacationPreference.objects.bulk_create(
            [
                VacationPreference(
                    employee=employee,
                    year=year,
                    priority=VacationPreference.PRIORITY_PRIMARY,
                    start_date=primary_start,
                    end_date=primary_end,
                    status=VacationPreference.STATUS_FILLED,
                    remainder_policy=remainder_policy,
                    comment=comment,
                ),
                VacationPreference(
                    employee=employee,
                    year=year,
                    priority=VacationPreference.PRIORITY_BACKUP,
                    start_date=backup_start,
                    end_date=backup_end,
                    status=VacationPreference.STATUS_FILLED,
                    remainder_policy=remainder_policy,
                    comment=comment,
                ),
            ]
        )

    def _set_skipped_preferences(self, employee, *, comment="Без пожеланий."):
        from apps.leave.models import VacationPreference

        year = self._year()
        VacationPreference.objects.filter(employee=employee, year=year).delete()
        VacationPreference.objects.bulk_create(
            [
                VacationPreference(
                    employee=employee,
                    year=year,
                    priority=VacationPreference.PRIORITY_PRIMARY,
                    status=VacationPreference.STATUS_SKIPPED,
                    comment=comment,
                ),
                VacationPreference(
                    employee=employee,
                    year=year,
                    priority=VacationPreference.PRIORITY_BACKUP,
                    status=VacationPreference.STATUS_SKIPPED,
                    comment=comment,
                ),
            ]
        )

    def _paid_period_for_chargeable_days(self, start_date, chargeable_days):
        from apps.leave.services.dates import get_chargeable_leave_days

        end_date = start_date
        while get_chargeable_leave_days(start_date, end_date, "paid") < chargeable_days:
            end_date += timedelta(days=1)
        return end_date

    def activate_only(self, *employees):
        ids = [employee.id for employee in employees]
        Employees.objects.exclude(id__in=ids).update(is_active_employee=False)
        Employees.objects.filter(id__in=ids).update(is_active_employee=True)

    def create_minimal_draft(self, *, year=None, created_by=None):
        from apps.leave.models import VacationSchedule

        return VacationSchedule.objects.create(
            year=year or self._year(),
            status=VacationSchedule.STATUS_DRAFT,
            created_by=created_by or self.hr_employee,
        )

    def create_employee_draft_item(
        self,
        employee,
        *,
        schedule=None,
        year=None,
        start_date,
        end_date=None,
        chargeable_days=None,
        source=None,
    ):
        from apps.leave.models import VacationScheduleItem
        from apps.leave.services.dates import get_chargeable_leave_days

        schedule = schedule or self.create_minimal_draft(year=year)
        end_date = end_date or start_date
        if chargeable_days is None:
            chargeable_days = get_chargeable_leave_days(start_date, end_date, "paid")
        return VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=employee,
            start_date=start_date,
            end_date=end_date,
            vacation_type="paid",
            chargeable_days=Decimal(str(chargeable_days)),
            status=VacationScheduleItem.STATUS_DRAFT,
            source=source or VacationScheduleItem.SOURCE_GENERATED,
            risk_score=0,
            risk_level=VacationScheduleItem.RISK_LOW,
        )

    def warm_manual_suggestion_cache(self, *, year=None, employee=None, limit=3):
        from apps.leave.services.schedule_drafts.manual_suggestions import build_schedule_draft_manual_suggestions

        kwargs = {
            "year": year or self._year(),
            "employee_id": (employee or self.employee).id,
        }
        kwargs["limit"] = limit
        return build_schedule_draft_manual_suggestions(**kwargs)
