from datetime import date

from django.urls import reverse
from django.utils import timezone

from apps.leave.models import VacationRequest, VacationSchedule, VacationScheduleItem
from apps.leave.services.schedule_changes import create_schedule_change_request

from .base import EmployeeTestCase
from ..page_contexts import _format_vacation_count_label


class EmployeeProfileTests(EmployeeTestCase):
    def test_planned_vacation_count_label_uses_russian_plural_forms(self):
        cases = (
            (0, "0 отпусков"),
            (1, "1 отпуск"),
            (2, "2 отпуска"),
            (4, "4 отпуска"),
            (5, "5 отпусков"),
            (11, "11 отпусков"),
            (21, "21 отпуск"),
            (24, "24 отпуска"),
        )

        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(_format_vacation_count_label(value), expected)

    def test_employee_cannot_view_another_profile(self):
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("employee_profile", args=[self.department_head.id]))

        self.assertRedirects(response, reverse("main"))

    def test_department_head_can_view_only_own_department_profile(self):
        self.client.force_login(self.department_head.user)

        own_department_response = self.client.get(reverse("employee_profile", args=[self.employee.id]))
        foreign_department_response = self.client.get(reverse("employee_profile", args=[self.outsider.id]))

        self.assertEqual(own_department_response.status_code, 200)
        self.assertRedirects(foreign_department_response, reverse("main"))

    def test_employee_profile_from_applications_keeps_applications_navigation(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("employee_profile", args=[self.employee.id]), {"from": "applications"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sidebar_section"], "applications")
        self.assertContains(response, "К заявкам")
        self.assertContains(response, "page-hero__center")
        self.assertContains(response, "page-hero__back-link")
        self.assertContains(response, 'data-section-back-link="applications"')
        self.assertContains(response, f'href="{reverse("applications")}"')
        self.assertContains(
            response,
            'data-sidebar-key="applications" aria-label="Заявки" title="Заявки" aria-current="page"',
        )
        self.assertNotContains(
            response,
            'data-sidebar-key="employees" aria-label="Сотрудники" title="Сотрудники" aria-current="page"',
        )

    def test_employee_profile_from_employees_keeps_employees_navigation(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("employee_profile", args=[self.employee.id]), {"from": "employees"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sidebar_section"], "employees")
        self.assertContains(response, "К сотрудникам")
        self.assertContains(response, "page-hero__center")
        self.assertContains(response, "page-hero__back-link")
        self.assertContains(response, 'data-section-back-link="employees"')
        self.assertContains(response, f'href="{reverse("employees")}"')
        self.assertContains(
            response,
            'data-sidebar-key="employees" aria-label="Сотрудники" title="Сотрудники" aria-current="page"',
        )

    def test_employee_profile_without_source_does_not_show_section_back_link(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("employee_profile", args=[self.employee.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sidebar_section"], "employees")
        self.assertNotContains(response, "К заявкам")
        self.assertNotContains(response, "К сотрудникам")
        self.assertNotContains(response, "data-section-back-link")

    def test_employee_profile_from_calendar_keeps_calendar_navigation(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("employee_profile", args=[self.employee.id]), {"from": "calendar"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sidebar_section"], "calendar")
        self.assertContains(response, "К графику")
        self.assertNotContains(response, "data-section-back-link")

    def test_employee_profile_ignores_unknown_source(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("employee_profile", args=[self.employee.id]), {"from": "unknown"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sidebar_section"], "employees")
        self.assertNotContains(response, "data-section-back-link")

    def test_employee_profile_from_departments_keeps_departments_navigation(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("employee_profile", args=[self.employee.id]), {"from": "departments"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sidebar_section"], "departments")
        self.assertContains(response, "К отделам")
        self.assertContains(response, 'data-section-back-link="departments"')
        self.assertContains(
            response,
            'data-sidebar-key="departments" aria-label="Отделы" title="Отделы" aria-current="page"',
        )
        self.assertNotContains(
            response,
            'data-sidebar-key="employees" aria-label="Сотрудники" title="Сотрудники" aria-current="page"',
        )

    def test_employee_profile_uses_explicit_back_link_to_department_group(self):
        department_group_url = f"{reverse('department_detail', args=[self.engineering.id])}?group={self.engineering_group.id}"
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(
            reverse("employee_profile", args=[self.employee.id]),
            {
                "from": "departments",
                "back_url": department_group_url,
                "back_label": "К группам",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sidebar_section"], "departments")
        self.assertContains(response, "К группам")
        self.assertContains(response, f'href="{department_group_url}"')
        self.assertNotContains(response, 'data-section-back-link="departments"')

    def test_employee_profile_from_vacation_detail_returns_to_that_request(self):
        request_obj = VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-12-15",
            end_date="2026-12-17",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(
            reverse("employee_profile", args=[self.employee.id]),
            {"from": "applications", "return_to": "vacation", "vacation_id": request_obj.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sidebar_section"], "applications")
        self.assertContains(response, "К заявке")
        self.assertContains(response, f'href="{reverse("vacation_detail", args=[request_obj.id])}?from=applications"')
        self.assertNotContains(response, 'data-section-back-link="applications"')

    def test_employee_profile_ignores_applications_source_without_access(self):
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("employee_profile", args=[self.employee.id]), {"from": "applications"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sidebar_section"], "profile")
        self.assertNotContains(response, "К заявкам")
        self.assertNotContains(response, "data-section-back-link")

    def test_main_page_uses_dedicated_template_for_regular_employee(self):
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("main"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "main.html")
        self.assertNotContains(response, 'data-modal-open="employee-edit-modal"')
        self.assertNotContains(response, 'id="employee-edit-modal"')
        self.assertContains(response, "js/employee-form.js")
        self.assertNotContains(response, "js/employees-page.js")
        self.assertNotContains(response, "page-hero__chip")
        self.assertContains(response, "Сводка сотрудника")
        self.assertContains(response, "employee-summary__identity")
        self.assertContains(response, "employee-summary__details")
        self.assertContains(response, "employee-summary__joined-row")
        self.assertContains(response, 'class="employee-summary__detail-card ', count=5)
        self.assertContains(response, "employee-summary__detail-card--position")
        self.assertContains(response, "employee-summary__detail-card--department")
        self.assertContains(response, "employee-summary__detail-card--group")
        self.assertContains(response, "employee-summary__detail-card--login")
        self.assertContains(response, "employee-summary__detail-card--status")
        self.assertNotContains(response, "employee-summary__meta")
        self.assertNotContains(response, "employee-summary__status")
        self.assertNotContains(response, "employee-summary__markers")
        self.assertContains(response, self.employee.position)
        self.assertContains(response, self.engineering.name)
        self.assertContains(response, self.engineering_group.name)
        self.assertContains(response, self.employee.login)
        self.assertContains(response, "Группа отдела")
        self.assertContains(response, "Доступный отпуск")
        self.assertContains(response, "Ближайший отпуск")
        self.assertContains(response, "Запланировано в этом году")
        self.assertContains(response, "Осталось")
        self.assertContains(response, "event_upcoming")
        self.assertContains(response, "Заявки в ожидании")
        self.assertContains(response, "Дата начала работы")
        self.assertContains(response, "Баланс по рабочим годам")
        self.assertContains(response, "Рабочий год")
        self.assertContains(response, "Право")
        self.assertContains(response, "Использовано")
        self.assertContains(response, "В резерве")
        self.assertContains(response, "Остаток")
        self.assertContains(response, "Использовать до")
        self.assertNotContains(response, "Показать расшифровку баланса")
        self.assertNotContains(response, 'id="employee-balance-modal"')
        self.assertContains(response, 'data-profile-section="schedule"')
        self.assertNotContains(response, "Начислено по стажу")
        self.assertNotContains(response, "Факт. баланс")
        self.assertNotContains(response, "Авансом")
        self.assertContains(response, "Статус")
        self.assertContains(response, "Работает")
        self.assertContains(response, "employee-status-badge employee-status-badge--working")

    def test_hr_main_page_renders_with_edit_modal(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("main"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-modal-open="employee-edit-modal"')
        self.assertContains(response, 'id="employee-edit-modal"')
        self.assertContains(response, 'name="role"')
        self.assertContains(response, 'data-employee-form')
        self.assertContains(response, 'data-employee-submit')
        self.assertNotContains(response, 'id="edit_employee_annual_paid_leave_days"')
        self.assertContains(response, "employee-summary__marker--hr")
        self.assertContains(response, "employee-summary__detail-card--login")
        content = response.content.decode(response.charset or "utf-8")
        self.assertLess(
            content.index("employee-summary__marker--hr"),
            content.index("Дата начала работы"),
        )

    def test_employee_profile_renders_with_edit_modal_for_hr(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("employee_profile", args=[self.employee.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="employee-edit-modal"')
        self.assertContains(response, 'name="role"')
        self.assertContains(response, 'app-modal__dialog app-modal__dialog--employee')
        self.assertNotContains(response, 'id="edit_employee_annual_paid_leave_days"')
        self.assertContains(response, "Сводка сотрудника")
        self.assertContains(response, "employee-summary__identity")
        self.assertContains(response, "employee-summary__details")
        self.assertContains(response, 'class="employee-summary__detail-card ', count=5)
        self.assertContains(response, "employee-summary__detail-card--position")
        self.assertContains(response, "employee-summary__detail-card--department")
        self.assertContains(response, "employee-summary__detail-card--group")
        self.assertContains(response, "employee-summary__detail-card--login")
        self.assertContains(response, "employee-summary__detail-card--status")
        self.assertNotContains(response, "employee-summary__meta")
        self.assertNotContains(response, "employee-summary__status")
        self.assertNotContains(response, "employee-summary__markers")
        self.assertContains(response, self.employee.position)
        self.assertContains(response, self.engineering.name)
        self.assertContains(response, self.engineering_group.name)
        self.assertContains(response, self.employee.login)
        self.assertContains(response, "Группа отдела")
        self.assertContains(response, "Доступный отпуск")
        self.assertContains(response, "Ближайший отпуск")
        self.assertContains(response, "Запланировано в этом году")
        self.assertContains(response, "Осталось")
        self.assertContains(response, "event_upcoming")
        self.assertContains(response, "Баланс по рабочим годам")
        self.assertContains(response, "Рабочий год")
        self.assertContains(response, "Право")
        self.assertContains(response, "Использовано")
        self.assertContains(response, "В резерве")
        self.assertContains(response, "Остаток")
        self.assertContains(response, "Использовать до")
        self.assertNotContains(response, "Показать расшифровку баланса")
        self.assertNotContains(response, 'id="employee-balance-modal"')
        self.assertNotContains(response, "Начислено по стажу")
        self.assertContains(response, "Статус")
        self.assertContains(response, "Работает")
        self.assertContains(response, "employee-status-badge employee-status-badge--working")
        self.assertContains(response, 'data-modal-open="employee-delete-modal"')
        self.assertContains(response, 'id="employee-delete-modal"')
        self.assertContains(response, reverse("delete_employee", args=[self.employee.id]))

    def test_employee_profile_highlights_department_deputy(self):
        self.engineering.deputy = self.employee
        self.engineering.save(update_fields=["deputy"])
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("employee_profile", args=[self.employee.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "employee-summary__role--department-deputy")
        self.assertContains(response, "employee-summary__marker--department-deputy")
        self.assertContains(response, "employee-summary__joined-row")
        self.assertContains(response, "supervisor_account")
        self.assertContains(response, "Заместитель отдела")
        content = response.content.decode(response.charset or "utf-8")
        self.assertLess(
            content.index("employee-summary__marker--department-deputy"),
            content.index("Дата начала работы"),
        )

    def test_employee_profile_places_management_role_before_joined_date(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("employee_profile", args=[self.department_head.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "employee-summary__role--department-head")
        self.assertContains(response, "employee-summary__marker--department-head")
        self.assertContains(response, "Руководитель отдела")
        content = response.content.decode(response.charset or "utf-8")
        self.assertLess(
            content.index("employee-summary__marker--department-head"),
            content.index("Дата начала работы"),
        )

    def test_employee_profile_shows_schedule_filters_and_confirmed_vacations(self):
        year = timezone.localdate().year
        schedule = VacationSchedule.objects.create(
            year=year,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(year, 10, 1),
            end_date=date(year, 10, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(year, 1, 10),
            end_date=date(year, 1, 15),
            vacation_type="paid",
            chargeable_days=6,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        archive_schedule = VacationSchedule.objects.create(
            year=year - 1,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        VacationScheduleItem.objects.create(
            schedule=archive_schedule,
            employee=self.employee,
            start_date=date(year - 1, 9, 1),
            end_date=date(year - 1, 9, 7),
            vacation_type="paid",
            chargeable_days=7,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("employee_profile", args=[self.employee.id]))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertContains(response, "Отпуска и график")
        self.assertContains(response, 'aria-label="Год отображения отпусков"')
        self.assertContains(response, 'aria-label="Тип отпуска"')
        self.assertNotContains(response, 'data-profile-schedule-period')
        self.assertNotContains(response, "profile-schedule-filter__label")
        self.assertContains(response, "Все")
        self.assertContains(response, "Оплачиваемые")
        self.assertContains(response, "Неоплачиваемые")
        self.assertContains(response, "Учебные")
        self.assertContains(response, "profile-schedule-calendar-select")
        self.assertContains(response, 'data-profile-schedule-year')
        self.assertContains(response, '<option value="all">Все</option>', html=False)
        self.assertContains(response, f'<option value="{year}" selected>{year}</option>', html=False)
        self.assertContains(response, f'<option value="{year - 1}"', html=False)
        self.assertContains(response, f"Отпуска на {year} год")
        self.assertContains(response, "20 д. / 2 отпуска")
        self.assertContains(response, "01.10.{} - 14.10.{}".format(year, year))
        self.assertContains(response, 'data-schedule-entry-card')
        self.assertContains(response, 'data-vacation-type="paid"')
        self.assertContains(response, 'data-source-kind="schedule"')
        self.assertContains(response, "Источник")
        self.assertContains(response, "Годовой график")
        self.assertNotContains(response, "Переносы отпусков")
        self.assertLess(
            html.index("01.10.{} - 14.10.{}".format(year, year)),
            html.index("10.01.{} - 15.01.{}".format(year, year)),
        )
        self.assertLess(
            html.index("10.01.{} - 15.01.{}".format(year, year)),
            html.index("01.09.{} - 07.09.{}".format(year - 1, year - 1)),
        )

    def test_employee_profile_schedule_contains_only_confirmed_absences(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-05-01",
            end_date="2026-05-03",
            vacation_type="unpaid",
            status=VacationRequest.STATUS_APPROVED,
        )
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-06-01",
            end_date="2026-06-05",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-07-01",
            end_date="2026-07-05",
            vacation_type="study",
            status=VacationRequest.STATUS_REJECTED,
        )
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("main"))
        html = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "01.05.2026 - 03.05.2026")
        self.assertContains(response, 'data-vacation-type="unpaid"')
        self.assertContains(response, 'data-source-kind="request"')
        self.assertContains(response, "Одобренная заявка")
        self.assertNotIn('data-status="request-pending"', html)
        self.assertNotIn('data-status="request-rejected"', html)
        self.assertContains(response, "01.06.2026 - 05.06.2026")
        self.assertContains(response, "01.07.2026 - 05.07.2026")
        self.assertContains(response, "История заявок")
        self.assertContains(response, "Все отправленные заявки: ожидание, одобрение и отклонение.")

    def test_employee_profile_shows_schedule_changes_only_when_present(self):
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        schedule_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        create_schedule_change_request(
            schedule_item.id,
            requested_by=self.employee,
            new_start_date=date(2026, 8, 1),
            new_end_date=date(2026, 8, 14),
            reason="Нужно перенести отпуск.",
        )
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("employee_profile", args=[self.employee.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Переносы отпусков")
        self.assertContains(response, 'data-schedule-transfer-card data-years="2026"', html=False)
        self.assertContains(response, "01.07.2026 - 14.07.2026")
        self.assertContains(response, "01.08.2026 - 14.08.2026")
        self.assertContains(response, "В ожидании")

    def test_enterprise_head_can_view_profile_without_edit_modal(self):
        self.client.force_login(self.enterprise_head.user)

        response = self.client.get(reverse("employee_profile", args=[self.employee.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="employee-edit-modal"')
        self.assertNotContains(response, 'data-modal-open="employee-delete-modal"')

    def test_main_page_renders_requests_as_cards_without_table_header(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-09-04",
            end_date="2026-09-12",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("main"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="vacation-request-card is-clickable"')
        self.assertContains(response, "Период")
        self.assertContains(response, "04.09.2026 - 12.09.2026")
        self.assertContains(response, "Тип")
        self.assertContains(response, "Статус")
        self.assertNotContains(response, ">Дата начала<", html=False)
        self.assertNotContains(response, ">Дата окончания<", html=False)
        self.assertNotContains(response, ">Тип отпуска<", html=False)
        self.assertNotContains(response, "<thead>", html=False)

    def test_main_page_empty_requests_state_does_not_render_table_markup(self):
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("main"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Заявок на отпуск пока нет.")
        self.assertNotContains(response, "<table", html=False)
