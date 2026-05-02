from datetime import date

from django.urls import reverse

from apps.leave.models import VacationRequest, VacationSchedule, VacationScheduleItem
from apps.leave.services.schedule_changes import create_schedule_change_request

from .base import LeaveTestCase


class ApplicationsBoardTests(LeaveTestCase):
    def test_applications_ajax_returns_only_department_scope_for_department_head(self):
        request_obj = VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-11-01",
            end_date="2026-11-03",
            vacation_type="study",
            status=VacationRequest.STATUS_PENDING,
        )
        VacationRequest.objects.create(
            employee=self.outsider,
            start_date="2026-11-05",
            end_date="2026-11-07",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        self.client.force_login(self.department_head.user)

        response = self.client.get(
            reverse("applications"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["vacations"]), 1)
        self.assertEqual(payload["vacations"][0]["employee_name"], self.employee.full_name)
        self.assertEqual(payload["vacations"][0]["employee_department"], self.employee.department.name)
        self.assertEqual(payload["vacations"][0]["detail_url"], reverse("vacation_detail", args=[request_obj.id]))
        self.assertEqual(
            payload["vacations"][0]["profile_url"],
            f'{reverse("employee_profile", args=[self.employee.id])}?from=applications',
        )
        self.assertEqual(payload["vacations"][0]["employee_role_icon"], "person")
        self.assertEqual(payload["vacations"][0]["employee_role_icon_type"], "material")
        self.assertEqual(payload["vacations"][0]["employee_role_variant"], "employee")
        self.assertEqual(payload["vacations"][0]["employee_role_label"], "Сотрудник")
        self.assertEqual(payload["vacations"][0]["employee_secondary_label"], self.employee.department.name)
        self.assertEqual(payload["vacations"][0]["period_label"], "01.11.2026 - 03.11.2026")
        self.assertIn("period_label", payload["vacations"][0])
        self.assertIn("vacations_html", payload)
        self.assertIn("change_requests_html", payload)
        self.assertIn(f'data-vacation-id="{request_obj.id}"', payload["vacations_html"])
        self.assertIn(f'data-href="{reverse("vacation_detail", args=[request_obj.id])}"', payload["vacations_html"])
        self.assertIn(f'href="{reverse("employee_profile", args=[self.employee.id])}?from=applications"', payload["vacations_html"])
        self.assertIn("application-card__profile-icon application-card__profile-icon--employee", payload["vacations_html"])
        self.assertIn('aria-label="Открыть профиль сотрудника', payload["vacations_html"])
        self.assertIn('<span class="application-card__label">ФИО</span>', payload["vacations_html"])
        self.assertIn("01.11.2026 - 03.11.2026", payload["vacations_html"])
        self.assertNotIn("ноября", payload["vacations_html"])
        self.assertNotIn('<span class="application-card__label">Сотрудник</span>', payload["vacations_html"])
        self.assertNotIn("<span>Профиль</span>", payload["vacations_html"])
        self.assertIn('role="link"', payload["vacations_html"])

    def test_applications_search_filters_requests_and_transfers_by_employee_name(self):
        request_obj = VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-11-01",
            end_date="2026-11-03",
            vacation_type="study",
            status=VacationRequest.STATUS_PENDING,
        )
        VacationRequest.objects.create(
            employee=self.outsider,
            start_date="2026-11-05",
            end_date="2026-11-07",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
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
        change_request = create_schedule_change_request(
            schedule_item.id,
            requested_by=self.employee,
            new_start_date=date(2026, 8, 1),
            new_end_date=date(2026, 8, 14),
            reason="Search test",
        )
        self.client.force_login(self.department_head.user)

        response = self.client.get(
            reverse("applications"),
            {
                "status": VacationRequest.STATUS_PENDING,
                "search": self.employee.first_name,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["id"] for item in payload["vacations"]], [request_obj.id])
        self.assertEqual([item["id"] for item in payload["change_requests"]], [change_request.id])
        self.assertIn(f'data-vacation-id="{request_obj.id}"', payload["vacations_html"])
        self.assertIn(f'data-change-request-id="{change_request.id}"', payload["change_requests_html"])
        self.assertIn(f'href="{reverse("employee_profile", args=[self.employee.id])}?from=applications"', payload["change_requests_html"])
        self.assertIn("application-card__profile-icon application-card__profile-icon--employee", payload["change_requests_html"])
        self.assertIn('<span class="application-card__label">ФИО</span>', payload["change_requests_html"])
        self.assertNotIn('<span class="application-card__label">Сотрудник</span>', payload["change_requests_html"])
        self.assertNotIn("<span>Профиль</span>", payload["change_requests_html"])

    def test_applications_search_respects_department_head_scope(self):
        VacationRequest.objects.create(
            employee=self.outsider,
            start_date="2026-11-05",
            end_date="2026-11-07",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        self.client.force_login(self.department_head.user)

        response = self.client.get(
            reverse("applications"),
            {"search": self.outsider.first_name},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["vacations"], [])
        self.assertEqual(payload["change_requests"], [])
        self.assertIn("Заявки по выбранным фильтрам не найдены.", payload["vacations_html"])
        self.assertIn("Переносы графика по выбранным фильтрам не найдены.", payload["change_requests_html"])

    def test_applications_filters_requests_and_transfers_by_group(self):
        matching_request = VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-11-01",
            end_date="2026-11-03",
            vacation_type="study",
            status=VacationRequest.STATUS_PENDING,
        )
        VacationRequest.objects.create(
            employee=self.outsider,
            start_date="2026-11-05",
            end_date="2026-11-07",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        matching_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        foreign_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.outsider,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        matching_change = create_schedule_change_request(
            matching_item.id,
            requested_by=self.employee,
            new_start_date=date(2026, 8, 1),
            new_end_date=date(2026, 8, 14),
            reason="Group test",
        )
        create_schedule_change_request(
            foreign_item.id,
            requested_by=self.outsider,
            new_start_date=date(2026, 10, 1),
            new_end_date=date(2026, 10, 14),
            reason="Foreign group test",
        )
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(
            reverse("applications"),
            {"group": self.engineering_group.id},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["id"] for item in payload["vacations"]], [matching_request.id])
        self.assertEqual([item["id"] for item in payload["change_requests"]], [matching_change.id])
        self.assertIn(f'data-vacation-id="{matching_request.id}"', payload["vacations_html"])
        self.assertIn(f'data-change-request-id="{matching_change.id}"', payload["change_requests_html"])

    def test_applications_group_filter_marks_both_board_selects_selected(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(
            reverse("applications"),
            {"group": self.engineering_group.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_group"], str(self.engineering_group.id))
        self.assertContains(
            response,
            f'<option value="{self.engineering_group.id}" data-department-id="{self.engineering.id}"',
            count=2,
            html=False,
        )
        content = response.content.decode(response.charset or "utf-8")
        self.assertNotIn(
            f'<option value="{self.engineering_group.id}" data-department-id="{self.engineering.id}" hidden disabled',
            content,
        )
        self.assertContains(
            response,
            (
                'class="employee-select__option is-selected" '
                f'data-employee-select-option data-value="{self.engineering_group.id}"'
            ),
            count=2,
            html=False,
        )

    def test_applications_department_filter_hides_foreign_group_options(self):
        self.client.force_login(self.enterprise_head.user)

        response = self.client.get(
            reverse("applications"),
            {"department": self.engineering.id},
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode(response.charset or "utf-8")
        self.assertEqual(
            content.count(
                f'<option value="{self.hr_group.id}" data-department-id="{self.hr_department.id}" hidden disabled'
            ),
            2,
        )
        self.assertEqual(
            content.count(
                f'data-value="{self.hr_group.id}" data-department-id="{self.hr_department.id}" hidden disabled'
            ),
            2,
        )
        self.assertNotIn(
            f'<option value="{self.engineering_group.id}" data-department-id="{self.engineering.id}" hidden disabled',
            content,
        )

    def test_applications_filters_vacation_requests_by_type(self):
        study_request = VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-11-01",
            end_date="2026-11-03",
            vacation_type="study",
            status=VacationRequest.STATUS_PENDING,
        )
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-12-01",
            end_date="2026-12-03",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2027-01-10",
            end_date="2027-01-12",
            vacation_type="unpaid",
            status=VacationRequest.STATUS_PENDING,
        )
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
        change_request = create_schedule_change_request(
            schedule_item.id,
            requested_by=self.employee,
            new_start_date=date(2026, 8, 1),
            new_end_date=date(2026, 8, 14),
            reason="Type filter test",
        )
        self.client.force_login(self.department_head.user)

        response = self.client.get(
            reverse("applications"),
            {"vacation_type": "study"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["id"] for item in payload["vacations"]], [study_request.id])
        self.assertEqual([item["id"] for item in payload["change_requests"]], [change_request.id])
        self.assertIn("Учебный", payload["vacations_html"])
        self.assertNotIn("Оплачиваемый вне графика", payload["vacations_html"])
        self.assertIn(f'data-change-request-id="{change_request.id}"', payload["change_requests_html"])

    def test_department_head_applications_show_group_filter_without_department_select(self):
        self.client.force_login(self.department_head.user)

        response = self.client.get(reverse("applications"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="applications-transfers-group"')
        self.assertContains(response, 'id="applications-requests-group"')
        self.assertContains(response, "data-applications-group-filter", count=2)
        self.assertContains(response, 'id="vacation-type-filter"')
        self.assertContains(response, "Все отпуска")
        self.assertNotContains(response, 'id="department"')
        self.assertNotContains(response, 'id="applications-department-form"')
        self.assertContains(response, self.engineering_group.name)
        self.assertNotContains(response, self.hr_group.name)

    def test_applications_page_places_linked_department_and_group_filters_on_boards(self):
        self.client.force_login(self.enterprise_head.user)

        response = self.client.get(reverse("applications"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="applications-department-form"')
        self.assertContains(response, 'id="applications-transfers-department"')
        self.assertContains(response, 'id="applications-requests-department"')
        self.assertContains(response, 'id="applications-transfers-group"')
        self.assertContains(response, 'id="applications-requests-group"')
        self.assertContains(response, "data-applications-department-filter", count=2)
        self.assertContains(response, "data-applications-group-filter", count=2)

        content = response.content.decode(response.charset or "utf-8")
        self.assertLess(
            content.index('id="applications-status-form-transfers"'),
            content.index('id="applications-transfers-department"'),
        )
        self.assertLess(
            content.index('id="applications-transfers-department"'),
            content.index('id="applications-transfers-group"'),
        )
        self.assertLess(
            content.index('id="applications-transfers-group"'),
            content.index('id="applications-search-transfers"'),
        )
        self.assertLess(
            content.index('id="applications-status-form-requests"'),
            content.index('id="applications-requests-department"'),
        )
        self.assertLess(
            content.index('id="applications-requests-department"'),
            content.index('id="applications-requests-group"'),
        )
        self.assertLess(
            content.index('id="applications-requests-group"'),
            content.index('id="vacation-type-filter"'),
        )
        self.assertLess(
            content.index('id="vacation-type-filter"'),
            content.index('id="applications-search-requests"'),
        )

    def test_applications_combines_status_department_group_and_search_filters(self):
        matching_request = VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-11-01",
            end_date="2026-11-03",
            vacation_type="study",
            status=VacationRequest.STATUS_PENDING,
        )
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-12-01",
            end_date="2026-12-03",
            vacation_type="study",
            status=VacationRequest.STATUS_APPROVED,
        )
        VacationRequest.objects.create(
            employee=self.outsider,
            start_date="2026-11-05",
            end_date="2026-11-07",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        self.client.force_login(self.enterprise_head.user)

        response = self.client.get(
            reverse("applications"),
            {
                "status": VacationRequest.STATUS_PENDING,
                "department": self.engineering.id,
                "group": self.engineering_group.id,
                "search": self.employee.first_name,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["id"] for item in payload["vacations"]], [matching_request.id])
        self.assertEqual(payload["change_requests"], [])

    def test_applications_page_uses_sectioned_cards_and_custom_department_select(self):
        request_obj = VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-11-01",
            end_date="2026-11-03",
            vacation_type="study",
            status=VacationRequest.STATUS_PENDING,
        )
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
        change_request = create_schedule_change_request(
            schedule_item.id,
            requested_by=self.employee,
            new_start_date=date(2026, 8, 1),
            new_end_date=date(2026, 8, 14),
            reason="Проверка карточек.",
        )
        self.client.force_login(self.department_head.user)

        response = self.client.get(reverse("applications"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-applications-page")
        self.assertContains(response, "applications-board--transfers")
        self.assertContains(response, "applications-board--requests")
        self.assertContains(response, "data-applications-transfer-scroll")
        self.assertContains(response, "data-applications-request-scroll")
        self.assertContains(response, f'data-vacation-id="{request_obj.id}"')
        self.assertContains(response, f'data-change-request-id="{change_request.id}"')
        self.assertContains(response, reverse("employee_profile", args=[self.employee.id]))
        self.assertContains(response, "application-card__profile-icon application-card__profile-icon--employee")
        self.assertContains(response, '<span class="application-card__label">ФИО</span>')
        self.assertNotContains(response, '<span class="application-card__label">Сотрудник</span>')
        self.assertNotContains(response, "<span>Профиль</span>")
        self.assertContains(response, reverse("schedule_change_approve", args=[change_request.id]))
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, 'class="employee-select__native"')
        self.assertContains(response, "data-applications-group-filter", count=2)
        self.assertNotContains(response, 'id="applications-department-form"')
        self.assertNotContains(response, 'id="lineCustom"')
        self.assertNotContains(response, 'id="vacationsTableBody"')
        self.assertNotContains(response, 'id="changeRequestsTableBody"')

        content = response.content.decode(response.charset or "utf-8")
        self.assertLess(
            content.index("applications-board--transfers"),
            content.index("applications-board--requests"),
        )

    def test_applications_pending_filter_applies_to_requests_and_transfers(self):
        pending_request = VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-10-01",
            end_date="2026-10-03",
            vacation_type="unpaid",
            status=VacationRequest.STATUS_PENDING,
        )
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-10-10",
            end_date="2026-10-12",
            vacation_type="study",
            status=VacationRequest.STATUS_APPROVED,
        )
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
        change_request = create_schedule_change_request(
            schedule_item.id,
            requested_by=self.employee,
            new_start_date=date(2026, 8, 1),
            new_end_date=date(2026, 8, 14),
            reason="Нужно перенести отпуск.",
        )

        self.client.force_login(self.department_head.user)
        response = self.client.get(
            reverse("applications"),
            {"status": VacationRequest.STATUS_PENDING},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["id"] for item in payload["vacations"]], [pending_request.id])
        self.assertEqual([item["id"] for item in payload["change_requests"]], [change_request.id])
        self.assertEqual(payload["change_requests"][0]["employee_department"], self.employee.department.name)
        self.assertEqual(
            payload["change_requests"][0]["profile_url"],
            f'{reverse("employee_profile", args=[self.employee.id])}?from=applications',
        )
        self.assertEqual(payload["change_requests"][0]["employee_role_icon"], "person")
        self.assertEqual(payload["change_requests"][0]["employee_role_icon_type"], "material")
        self.assertEqual(payload["change_requests"][0]["employee_role_variant"], "employee")
        self.assertEqual(payload["change_requests"][0]["employee_role_label"], "Сотрудник")
        self.assertEqual(payload["change_requests"][0]["employee_secondary_label"], self.employee.department.name)
        self.assertEqual(payload["change_requests"][0]["employee_position_label"], self.employee.position)
        self.assertEqual(payload["change_requests"][0]["employee_department_label"], self.employee.department.name)
        self.assertEqual(payload["change_requests"][0]["employee_production_group_label"], self.engineering_group.name)
        self.assertIn("approve_url", payload["change_requests"][0])
        self.assertIn("reject_url", payload["change_requests"][0])
        self.assertIn(f'data-vacation-id="{pending_request.id}"', payload["vacations_html"])
        self.assertIn(f'data-change-request-id="{change_request.id}"', payload["change_requests_html"])
        self.assertIn(reverse("schedule_change_approve", args=[change_request.id]), payload["change_requests_html"])
        self.assertIn(reverse("schedule_change_reject", args=[change_request.id]), payload["change_requests_html"])
        self.assertIn('name="csrfmiddlewaretoken"', payload["change_requests_html"])

    def test_applications_employee_identity_uses_role_icons_and_secondary_labels(self):
        hr_request = VacationRequest.objects.create(
            employee=self.hr_employee,
            start_date="2026-12-01",
            end_date="2026-12-03",
            vacation_type="study",
            status=VacationRequest.STATUS_PENDING,
        )
        department_head_request = VacationRequest.objects.create(
            employee=self.department_head,
            start_date="2026-12-05",
            end_date="2026-12-07",
            vacation_type="study",
            status=VacationRequest.STATUS_PENDING,
        )
        self.client.force_login(self.enterprise_head.user)

        response = self.client.get(
            reverse("applications"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        requests_by_id = {item["id"]: item for item in payload["vacations"]}
        self.assertEqual(requests_by_id[hr_request.id]["employee_role_icon"], "manage_accounts")
        self.assertEqual(requests_by_id[hr_request.id]["employee_role_variant"], "hr")
        self.assertEqual(requests_by_id[hr_request.id]["employee_secondary_label"], self.hr_employee.department.name)
        self.assertEqual(requests_by_id[hr_request.id]["employee_position_label"], self.hr_employee.position)
        self.assertEqual(requests_by_id[hr_request.id]["employee_production_group_label"], self.hr_group.name)
        self.assertEqual(
            requests_by_id[department_head_request.id]["employee_role_icon"],
            "admin_panel_settings",
        )
        self.assertEqual(
            requests_by_id[department_head_request.id]["employee_role_variant"],
            "department-head",
        )
        self.assertEqual(
            requests_by_id[department_head_request.id]["employee_secondary_label"],
            self.department_head.position,
        )
        self.assertEqual(
            requests_by_id[department_head_request.id]["employee_management_badges"],
            [
                {
                    "label": "Руководитель отдела",
                    "icon": "admin_panel_settings",
                    "icon_type": "material",
                    "variant": "department-head",
                }
            ],
        )
        self.assertIn("application-card__profile-icon--hr", payload["vacations_html"])
        self.assertIn("application-card__profile-icon--department-head", payload["vacations_html"])
        self.assertIn("application-card__management-badge application-card__management-badge--department-head", payload["vacations_html"])
        self.assertIn("application-card__org-item--department", payload["vacations_html"])
        self.assertIn("application-card__org-item--group", payload["vacations_html"])
        self.assertIn(self.department_head.department.name, payload["vacations_html"])
        self.assertIn(self.engineering_leadership_group.name, payload["vacations_html"])
        self.assertNotIn("Отдел:", payload["vacations_html"])
        self.assertNotIn("Группа:", payload["vacations_html"])
        self.assertIn(self.department_head.position, payload["vacations_html"])

    def test_applications_identity_marks_department_deputy_like_employee_cards(self):
        self.engineering.deputy = self.employee
        self.engineering.save(update_fields=["deputy"])
        request_obj = VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-12-01",
            end_date="2026-12-03",
            vacation_type="study",
            status=VacationRequest.STATUS_PENDING,
        )
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
        change_request = create_schedule_change_request(
            schedule_item.id,
            requested_by=self.employee,
            new_start_date=date(2026, 8, 1),
            new_end_date=date(2026, 8, 14),
            reason="Deputy identity test",
        )
        self.client.force_login(self.department_head.user)

        response = self.client.get(
            reverse("applications"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        requests_by_id = {item["id"]: item for item in payload["vacations"]}
        changes_by_id = {item["id"]: item for item in payload["change_requests"]}
        for item in (requests_by_id[request_obj.id], changes_by_id[change_request.id]):
            self.assertEqual(item["employee_role_icon"], "supervisor_account")
            self.assertEqual(item["employee_role_variant"], "department-deputy")
            self.assertEqual(
                item["employee_management_badges"],
                [
                    {
                        "label": "Заместитель отдела",
                        "icon": "supervisor_account",
                        "icon_type": "material",
                        "variant": "department-deputy",
                    }
                ],
            )
            self.assertEqual(item["employee_position_label"], self.employee.position)
            self.assertEqual(item["employee_department_label"], self.engineering.name)
            self.assertEqual(item["employee_production_group_label"], self.engineering_group.name)
        self.assertIn("application-card__profile-icon--department-deputy", payload["vacations_html"])
        self.assertIn("application-card__management-badge application-card__management-badge--department-deputy", payload["vacations_html"])
        self.assertIn("application-card__management-badge application-card__management-badge--department-deputy", payload["change_requests_html"])
        self.assertIn(self.engineering.name, payload["vacations_html"])
        self.assertIn(self.engineering_group.name, payload["change_requests_html"])
        self.assertNotIn("Отдел:", payload["vacations_html"])
        self.assertNotIn("Группа:", payload["change_requests_html"])

    def test_applications_enterprise_head_identity_uses_crown_symbol(self):
        request_obj = VacationRequest.objects.create(
            employee=self.enterprise_head,
            start_date="2026-12-10",
            end_date="2026-12-12",
            vacation_type="study",
            status=VacationRequest.STATUS_PENDING,
        )
        self.client.force_login(self.authorized_person.user)

        response = self.client.get(
            reverse("applications"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        requests_by_id = {item["id"]: item for item in payload["vacations"]}
        self.assertEqual(requests_by_id[request_obj.id]["employee_role_icon"], "♛")
        self.assertEqual(requests_by_id[request_obj.id]["employee_role_icon_type"], "symbol")
        self.assertEqual(requests_by_id[request_obj.id]["employee_role_variant"], "enterprise-head")
        self.assertEqual(
            requests_by_id[request_obj.id]["employee_secondary_label"],
            self.enterprise_head.department.name,
        )
        self.assertIn("application-card__profile-icon--enterprise-head", payload["vacations_html"])
        self.assertIn('<span class="application-card__profile-symbol" aria-hidden="true">♛</span>', payload["vacations_html"])
