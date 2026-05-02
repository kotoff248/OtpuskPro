from datetime import date

from django.urls import reverse

from apps.accounts.services import sync_employee_user
from apps.employees.models import DepartmentCoverageRule, EmployeePosition, Employees, ProductionGroup, ProductionGroupSubstitutionRule
from apps.leave.models import DepartmentStaffingRule, VacationRequest, VacationSchedule, VacationScheduleItem
from apps.leave.services.calendar import build_calendar_base_data, build_calendar_rows
from apps.leave.services.requests import approve_vacation_request

from .base import LeaveTestCase


class CalendarTests(LeaveTestCase):
    def test_calendar_shows_converted_paid_request_only_as_schedule_item(self):
        VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        pending_request = VacationRequest.objects.create(
            employee=self.employee,
            start_date=date(2026, 10, 6),
            end_date=date(2026, 10, 12),
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )
        approved_request = approve_vacation_request(pending_request.id, reviewer=self.department_head)

        _, _, employee_entries = build_calendar_base_data(2026, employee_ids=[self.employee.id])
        entries = employee_entries[self.employee.id]

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["source_kind"], "schedule")
        self.assertEqual(entries[0]["source_label"], "Дополнение к графику")
        self.assertEqual(entries[0]["source_id"], approved_request.created_schedule_items.get().id)
        self.assertEqual(entries[0]["detail_url"], reverse("vacation_detail", args=[approved_request.id]))
        self.assertEqual(entries[0]["detail_label"], "Открыть заявку")

    def test_calendar_ajax_returns_partial_results_for_view_switch(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-07-10",
            end_date="2026-07-14",
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        self.client.force_login(self.employee.user)

        response = self.client.get(
            reverse("calendar"),
            {"view": "year", "year": 2026},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("board_html", payload)
        self.assertIn("period_label", payload)
        self.assertIn("period_description", payload)
        self.assertIn("calendar_details", payload)
        self.assertIn("year-board", payload["board_html"])
        self.assertNotIn("calendar-board-card", payload["board_html"])
        self.assertNotIn('id="calendar-filters-form"', payload["board_html"])
        self.assertNotIn("calendar-summary-grid", payload["board_html"])
        self.assertIn(str(self.employee.id), payload["calendar_details"])
        self.assertIn("timeline-employee-card__role", payload["board_html"])
        self.assertIn("timeline-employee-card__role--employee", payload["board_html"])
        self.assertNotIn("timeline-employee-card__profile-link", payload["board_html"])
        self.assertIn("timeline-employee-card__org-item--department", payload["board_html"])
        self.assertIn("timeline-employee-card__org-item--group", payload["board_html"])
        self.assertIn(self.employee.department.name, payload["board_html"])
        self.assertIn(self.engineering_group.name, payload["board_html"])
        self.assertNotIn("Отдел:", payload["board_html"])
        self.assertNotIn("Группа:", payload["board_html"])
        self.assertNotIn("timeline-employee-card__meta", payload["board_html"])
        self.assertNotIn(self.employee.position, payload["board_html"])
        self.assertIn(reverse("employee_profile", args=[self.employee.id]), payload["board_html"])
        self.assertEqual(payload["period_label"], "График отпусков на 2026 год")

        month_response = self.client.get(
            reverse("calendar"),
            {"view": "month", "year": 2026, "month": 7},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(month_response.status_code, 200)
        month_payload = month_response.json()
        self.assertEqual(month_payload["period_label"], "График отпусков на июль 2026")
        self.assertIn("timeline-employee-card__org-item--department", month_payload["board_html"])
        self.assertIn("timeline-employee-card__org-item--group", month_payload["board_html"])
        self.assertIn(self.employee.department.name, month_payload["board_html"])
        self.assertIn(self.engineering_group.name, month_payload["board_html"])
        self.assertNotIn("Отдел:", month_payload["board_html"])
        self.assertNotIn("Группа:", month_payload["board_html"])
        self.assertNotIn("timeline-employee-card__meta", month_payload["board_html"])
        self.assertNotIn(self.employee.position, month_payload["board_html"])

    def test_calendar_page_uses_shared_vacation_modal_hooks(self):
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("calendar"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["calendar_view_mode"], "year")
        self.assertContains(response, 'data-segmented-index="0"')
        self.assertLess(
            response.content.decode().index('value="year"'),
            response.content.decode().index('value="month"'),
        )
        self.assertContains(response, 'name="view" value="year" checked')
        self.assertContains(response, 'class="calendar-select__native" disabled')
        self.assertContains(response, "year-board")
        self.assertContains(response, 'data-modal-open="vacation-modal"')
        self.assertContains(response, 'id="vacation-modal"')
        self.assertContains(response, 'id="chargeable_days"')
        self.assertContains(response, 'id="available_on_start"')
        self.assertContains(response, 'id="entitlement_source_label"')
        self.assertContains(response, 'id="entitlement_source_list"')
        self.assertContains(response, "Источник дней")
        self.assertContains(response, 'id="calendar-charge-preview"')
        self.assertContains(response, 'data-preview-url')
        self.assertContains(response, 'name="reason"')
        self.assertContains(response, "Отправить заявку")
        self.assertContains(response, "Должность")
        self.assertNotContains(response, "Дата права на оплачиваемый отпуск")
        self.assertContains(response, 'data-modal-close')
        self.assertContains(response, 'data-date-field')
        self.assertContains(response, 'id="calendar-filters-form"', count=1)
        self.assertNotContains(response, "calendar-summary-grid")
        page_html = response.content.decode()
        self.assertContains(response, "calendar-drawer__employee-card")
        self.assertContains(response, "calendar-drawer__stats calendar-drawer__stats--hero")
        self.assertLess(
            page_html.index("calendar-drawer__employee-card"),
            page_html.index("calendar-drawer__stats calendar-drawer__stats--hero"),
        )
        self.assertLess(
            page_html.index("calendar-drawer__stats calendar-drawer__stats--hero"),
            page_html.index('class="calendar-drawer__body"'),
        )
        self.assertContains(response, 'id="calendar-detail-profile-link"')
        self.assertContains(response, "calendar-drawer__profile-link--employee")
        self.assertContains(response, 'id="calendar-detail-position"')
        self.assertContains(response, 'id="calendar-detail-department"')
        self.assertContains(response, 'id="calendar-detail-group"')
        self.assertContains(response, 'id="calendar-detail-management-badges"')
        self.assertNotContains(response, ">Открыть профиль</span>")
        self.assertContains(response, "timeline-employee-card__role")
        self.assertContains(response, "timeline-employee-card__role--employee")
        self.assertContains(response, 'role="button"')
        self.assertContains(response, reverse("employee_profile", args=[self.employee.id]))

    def test_calendar_detail_drawer_shows_management_role_badge(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("calendar"), {"employee": self.department_head.id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "calendar-drawer__employee-card")
        self.assertContains(response, "calendar-drawer__profile-link--department-head")
        self.assertContains(response, "calendar-drawer__employee-badge--department-head")
        self.assertContains(response, "Руководитель отдела")
        self.assertContains(response, self.department_head.position)
        self.assertContains(response, self.department_head.department.name)
        self.assertContains(response, self.engineering_leadership_group.name)

    def test_calendar_page_always_shows_paid_request_option(self):
        newcomer = Employees.objects.create(
            last_name="Фомин",
            first_name="Олег",
            middle_name="Олегович",
            login="newcomer-calendar-paid-visible",
            position="Инженер",
            department=self.engineering,
            date_joined=date(2026, 2, 16),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        sync_employee_user(newcomer, raw_password="newcomer-pass")
        self.client.force_login(newcomer.user)

        response = self.client.get(reverse("calendar"), {"view": "month", "year": 2026, "month": 4})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<option value="paid" selected>Ежегодный оплачиваемый</option>', html=True)
        self.assertContains(response, "Дата права на оплачиваемый отпуск")

    def test_vacation_request_preview_allows_new_hire_paid_leave_after_six_months(self):
        VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        newcomer = Employees.objects.create(
            last_name="Фомин",
            first_name="Олег",
            middle_name="Олегович",
            login="newcomer-preview-allowed",
            position="Инженер",
            department=self.engineering,
            date_joined=date(2026, 2, 16),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        sync_employee_user(newcomer, raw_password="newcomer-preview-pass")
        self.client.force_login(newcomer.user)

        response = self.client.get(
            reverse("vacation_request_preview"),
            {
                "start_date": "2026-10-10",
                "end_date": "2026-10-16",
                "vacation_type": "paid",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["can_submit"])
        self.assertEqual(payload["available_from"], "2026-08-16")
        self.assertGreater(payload["chargeable_days"], 0)
        self.assertEqual(payload["entitlement_source_label"], "Дни будут списаны из рабочего года 16.02.2026 - 15.02.2027")
        self.assertEqual(len(payload["entitlement_allocations"]), 1)
        self.assertEqual(payload["entitlement_allocations"][0]["period_label"], "16.02.2026 - 15.02.2027")
        self.assertIn("risk_explanation", payload)
        self.assertIn("risk_short_reason", payload)
        self.assertIn("risk_recommended_action", payload)
        self.assertAlmostEqual(
            payload["remaining_after_request"],
            payload["available_on_start"] - payload["chargeable_days"],
            places=2,
        )
        self.assertIn("Заявку можно отправить", payload["message"])

    def test_vacation_request_preview_blocks_paid_leave_before_six_months(self):
        VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        newcomer = Employees.objects.create(
            last_name="Фомин",
            first_name="Олег",
            middle_name="Олегович",
            login="newcomer-preview-blocked",
            position="Инженер",
            department=self.engineering,
            date_joined=date(2026, 2, 16),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        sync_employee_user(newcomer, raw_password="newcomer-blocked-pass")
        self.client.force_login(newcomer.user)

        response = self.client.get(
            reverse("vacation_request_preview"),
            {
                "start_date": "2026-06-10",
                "end_date": "2026-06-16",
                "vacation_type": "paid",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["can_submit"])
        self.assertEqual(payload["available_from"], "2026-08-16")
        self.assertIn("Оплачиваемый отпуск доступен с", payload["message"])

    def test_vacation_request_preview_does_not_charge_unpaid_or_study_leave(self):
        self.client.force_login(self.employee.user)

        for vacation_type in ("unpaid", "study"):
            with self.subTest(vacation_type=vacation_type):
                response = self.client.get(
                    reverse("vacation_request_preview"),
                    {
                        "start_date": "2026-08-10",
                        "end_date": "2026-08-12",
                        "vacation_type": vacation_type,
                    },
                )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertTrue(payload["can_submit"])
                self.assertEqual(payload["chargeable_days"], 0)
                self.assertEqual(payload["entitlement_source_label"], "Оплачиваемый баланс не списывается")
                self.assertEqual(payload["entitlement_allocations"], [])
                self.assertEqual(payload["available_on_start"], payload["remaining_after_request"])
                self.assertIn("не уменьшает оплачиваемый баланс", payload["message"])

    def test_vacation_request_preview_forbids_authorized_person(self):
        self.client.force_login(self.authorized_person.user)

        response = self.client.get(
            reverse("vacation_request_preview"),
            {
                "start_date": "2026-08-10",
                "end_date": "2026-08-12",
                "vacation_type": "unpaid",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()["can_submit"])

    def test_calendar_page_renders_only_visible_employee_rows_for_regular_employee(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-11-01",
            end_date="2026-11-03",
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        VacationRequest.objects.create(
            employee=self.outsider,
            start_date="2026-11-05",
            end_date="2026-11-07",
            vacation_type="paid",
            status=VacationRequest.STATUS_APPROVED,
        )
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("calendar"), {"view": "year", "year": 2026})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.employee.full_name)
        self.assertNotContains(response, self.outsider.full_name)

    def test_calendar_filters_by_department_and_search(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(
            reverse("calendar"),
            {
                "view": "year",
                "year": 2026,
                "department": self.engineering.id,
                "search": self.employee.first_name,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["calendar_filters"]["selected_department"], str(self.engineering.id))
        self.assertEqual(response.context["calendar_filters"]["search_query"], self.employee.first_name)
        self.assertContains(response, self.employee.full_name)
        self.assertNotContains(response, self.outsider.full_name)

    def test_calendar_invalid_department_filter_resets_to_all(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("calendar"), {"view": "year", "year": 2026, "department": 999999})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["calendar_filters"]["selected_department"], "all")
        self.assertContains(response, self.employee.full_name)
        self.assertContains(response, self.outsider.full_name)

    def test_calendar_issue_filter_shows_only_high_risk_rows(self):
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 10),
            vacation_type="paid",
            chargeable_days=10,
            status=VacationScheduleItem.STATUS_APPROVED,
            risk_level=VacationScheduleItem.RISK_HIGH,
            risk_score=88,
        )
        VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.outsider,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 10),
            vacation_type="paid",
            chargeable_days=10,
            status=VacationScheduleItem.STATUS_APPROVED,
            risk_level=VacationScheduleItem.RISK_LOW,
            risk_score=10,
        )
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("calendar"), {"view": "year", "year": 2026, "issue": "risk"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["calendar_filters"]["selected_issue"], "risk")
        self.assertContains(response, self.employee.full_name)
        self.assertContains(response, "Высокий риск: 88%")
        self.assertNotContains(response, self.outsider.full_name)
        detail = response.context["calendar_details"][str(self.employee.id)]
        self.assertTrue(detail["has_high_risk"])
        self.assertFalse(detail["has_conflict"])
        self.assertEqual(detail["issue_label"], "Высокий риск")
        self.assertEqual(detail["risk_details"]["status"], "risk")
        self.assertEqual(detail["risk_details"]["label"], "Высокий риск")
        self.assertTrue(
            any("88%" in problem["text"] for problem in detail["risk_details"]["problems"])
        )
        self.assertEqual(detail["selected_entries"][0]["risk_score"], 88)
        self.assertEqual(detail["selected_entries"][0]["risk_label"], "Высокий")
        self.assertTrue(detail["selected_entries"][0]["has_high_risk"])
        self.assertEqual(detail["selected_entries"][0]["anchor"]["employee_id"], self.employee.id)

        month_response = self.client.get(
            reverse("calendar"),
            {"view": "month", "year": 2026, "month": 4, "issue": "risk"},
        )
        self.assertNotContains(month_response, self.employee.full_name)

    def test_calendar_month_drawer_splits_selected_month_and_other_year_entries(self):
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        may_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2026, 5, 10),
            end_date=date(2026, 5, 14),
            vacation_type="paid",
            chargeable_days=5,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        july_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 7),
            vacation_type="paid",
            chargeable_days=7,
            status=VacationScheduleItem.STATUS_APPROVED,
        )

        employees, employee_day_status, employee_entries = build_calendar_base_data(
            2026,
            employee_ids=[self.employee.id],
        )
        _, details = build_calendar_rows(
            employees,
            employee_day_status,
            employee_entries,
            year=2026,
            month=5,
            view_mode="month",
            today=date(2026, 5, 1),
        )

        detail = details[str(self.employee.id)]
        self.assertEqual(detail["view_mode"], "month")
        self.assertFalse(detail["is_year_view"])
        self.assertEqual(detail["primary_entries_title"], "Отпуска в выбранном месяце")
        self.assertEqual([entry["source_id"] for entry in detail["primary_entries"]], [may_item.id])
        self.assertEqual([entry["source_id"] for entry in detail["secondary_entries"]], [july_item.id])
        self.assertEqual(len(detail["year_entries"]), 2)

    def test_calendar_year_drawer_uses_single_primary_entries_list(self):
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        first_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2026, 5, 10),
            end_date=date(2026, 5, 14),
            vacation_type="paid",
            chargeable_days=5,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        second_item = VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 7),
            vacation_type="paid",
            chargeable_days=7,
            status=VacationScheduleItem.STATUS_APPROVED,
        )

        employees, employee_day_status, employee_entries = build_calendar_base_data(
            2026,
            employee_ids=[self.employee.id],
        )
        _, details = build_calendar_rows(
            employees,
            employee_day_status,
            employee_entries,
            year=2026,
            month=5,
            view_mode="year",
            today=date(2026, 5, 1),
        )

        detail = details[str(self.employee.id)]
        self.assertEqual(detail["view_mode"], "year")
        self.assertTrue(detail["is_year_view"])
        self.assertEqual(detail["primary_entries_title"], "Записи за год")
        self.assertEqual(
            [entry["source_id"] for entry in detail["primary_entries"]],
            [first_item.id, second_item.id],
        )
        self.assertEqual(detail["secondary_entries"], [])

    def test_calendar_issue_filter_shows_only_staffing_conflicts(self):
        DepartmentStaffingRule.objects.create(
            department=self.engineering,
            min_staff_required=1,
            max_absent=1,
            criticality_level=3,
        )
        coworker = Employees.objects.create(
            last_name="Соседов",
            first_name="Артем",
            middle_name="Иванович",
            login="calendar-conflict-coworker",
            position="Инженер",
            department=self.engineering,
            date_joined=date(2024, 1, 10),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        sync_employee_user(coworker, raw_password="coworker-pass")
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        for employee in (self.employee, coworker):
            VacationScheduleItem.objects.create(
                schedule=schedule,
                employee=employee,
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 7),
                vacation_type="paid",
                chargeable_days=7,
                status=VacationScheduleItem.STATUS_APPROVED,
            )
        VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.outsider,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 7),
            vacation_type="paid",
            chargeable_days=7,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("calendar"), {"view": "month", "year": 2026, "month": 8, "issue": "conflict"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["calendar_filters"]["selected_issue"], "conflict")
        self.assertContains(response, self.employee.full_name)
        self.assertContains(response, coworker.full_name)
        self.assertContains(response, "Конфликт: отсутствуют 2")
        self.assertNotContains(response, self.outsider.full_name)
        detail = response.context["calendar_details"][str(self.employee.id)]
        self.assertTrue(detail["has_conflict"])
        self.assertEqual(detail["issue_label"], "Конфликт")
        self.assertEqual(detail["risk_details"]["status"], "conflict")
        problem = detail["risk_details"]["problems"][0]
        self.assertEqual(problem["period_label"], "1-7 августа")
        self.assertEqual(problem["title"], "Превышен лимит отсутствующих")
        self.assertIn("отсутствуют 2 сотрудника при лимите 1 сотрудник", problem["text"])
        self.assertEqual(problem["impact_label"], "Превышение: 1 сотрудник")
        self.assertIn("Календарев Иван", problem["affected_names"])
        self.assertIn("Соседов Артем", problem["affected_names"])
        self.assertIn("отсутствуют 2", detail["conflict_summary"])
        self.assertTrue(detail["selected_entries"][0]["has_conflict"])
        self.assertIn("отсутствуют 2", detail["selected_entries"][0]["conflict_summary"])
        self.assertEqual(detail["selected_entries"][0]["risk_short_reason"], "")

    def test_calendar_conflict_detects_production_group_shortage(self):
        DepartmentStaffingRule.objects.create(
            department=self.engineering,
            min_staff_required=0,
            max_absent=10,
            criticality_level=3,
        )
        DepartmentCoverageRule.objects.create(
            department=self.engineering,
            production_group=self.engineering_group,
            min_staff_required=1,
            max_absent=5,
            criticality_level=5,
        )
        coworker = Employees.objects.create(
            last_name="Группов",
            first_name="Артем",
            middle_name="Иванович",
            login="calendar-group-coworker",
            position="Инженер",
            employee_position=self.engineering_engineer_position,
            department=self.engineering,
            date_joined=date(2024, 1, 10),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        for employee in (self.employee, coworker):
            VacationScheduleItem.objects.create(
                schedule=schedule,
                employee=employee,
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 7),
                vacation_type="paid",
                chargeable_days=7,
                status=VacationScheduleItem.STATUS_APPROVED,
            )
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("calendar"), {"view": "month", "year": 2026, "month": 9, "issue": "conflict"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.employee.full_name)
        self.assertContains(response, coworker.full_name)
        detail = response.context["calendar_details"][str(self.employee.id)]
        self.assertTrue(detail["has_conflict"])
        self.assertIn("не хватает: Инженеры", detail["conflict_summary"])

    def test_calendar_conflict_details_group_adjacent_days_into_period(self):
        DepartmentStaffingRule.objects.create(
            department=self.engineering,
            min_staff_required=0,
            max_absent=10,
            criticality_level=3,
        )
        DepartmentCoverageRule.objects.create(
            department=self.engineering,
            production_group=self.engineering_group,
            min_staff_required=0,
            max_absent=1,
            criticality_level=5,
        )
        coworker = Employees.objects.create(
            last_name="Белов",
            first_name="Андрей",
            middle_name="Андреевич",
            login="calendar-below-conflict",
            position="Инженер",
            employee_position=self.engineering_engineer_position,
            department=self.engineering,
            date_joined=date(2024, 1, 10),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        for employee in (self.employee, coworker):
            VacationScheduleItem.objects.create(
                schedule=schedule,
                employee=employee,
                start_date=date(2026, 7, 22),
                end_date=date(2026, 7, 23),
                vacation_type="paid",
                chargeable_days=2,
                status=VacationScheduleItem.STATUS_APPROVED,
            )
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("calendar"), {"view": "month", "year": 2026, "month": 7, "issue": "conflict"})

        detail = response.context["calendar_details"][str(self.employee.id)]
        problems = detail["risk_details"]["problems"]
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["period_label"], "22-23 июля")
        self.assertEqual(problems[0]["title"], "Превышен лимит отсутствующих")
        self.assertIn("Инженеры: отсутствуют 2 сотрудника при лимите 1 сотрудник", problems[0]["text"])
        self.assertEqual(problems[0]["impact_label"], "Превышение: 1 сотрудник")
        self.assertIn("Белов Андрей", problems[0]["affected_names"])

    def test_calendar_conflict_details_merge_group_limit_and_shortage(self):
        DepartmentStaffingRule.objects.create(
            department=self.engineering,
            min_staff_required=0,
            max_absent=10,
            criticality_level=3,
        )
        DepartmentCoverageRule.objects.create(
            department=self.engineering,
            production_group=self.engineering_group,
            min_staff_required=2,
            max_absent=1,
            criticality_level=5,
        )
        coworker = Employees.objects.create(
            last_name="Разный",
            first_name="Артем",
            middle_name="Иванович",
            login="calendar-different-problem-kind",
            position="Инженер",
            employee_position=self.engineering_engineer_position,
            department=self.engineering,
            date_joined=date(2024, 1, 10),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        for employee in (self.employee, coworker):
            VacationScheduleItem.objects.create(
                schedule=schedule,
                employee=employee,
                start_date=date(2026, 7, 22),
                end_date=date(2026, 7, 23),
                vacation_type="paid",
                chargeable_days=2,
                status=VacationScheduleItem.STATUS_APPROVED,
            )
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("calendar"), {"view": "month", "year": 2026, "month": 7, "issue": "conflict"})

        detail = response.context["calendar_details"][str(self.employee.id)]
        problems = detail["risk_details"]["problems"]
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["kind"], "group_staffing_combined")
        self.assertEqual(problems[0]["title"], "Группа не проходит по составу")
        self.assertEqual(problems[0]["period_label"], "22-23 июля")
        self.assertIn("Инженеры: отсутствуют 2 сотрудника, останется 0 сотрудников", problems[0]["text"])
        self.assertEqual(problems[0]["impact_label"], "Не хватает: 2 сотрудника")
        self.assertIn("Календарев Иван", problems[0]["affected_names"])
        self.assertIn("Разный Артем", problems[0]["affected_names"])

    def test_calendar_conflict_details_keep_separate_group_staffing_periods(self):
        DepartmentStaffingRule.objects.create(
            department=self.engineering,
            min_staff_required=0,
            max_absent=10,
            criticality_level=3,
        )
        DepartmentCoverageRule.objects.create(
            department=self.engineering,
            production_group=self.engineering_group,
            min_staff_required=2,
            max_absent=1,
            criticality_level=5,
        )
        coworker = Employees.objects.create(
            last_name="Периодов",
            first_name="Артем",
            middle_name="Иванович",
            login="calendar-different-period-kind",
            position="Инженер",
            employee_position=self.engineering_engineer_position,
            department=self.engineering,
            date_joined=date(2024, 1, 10),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        for start_date, end_date in ((date(2026, 7, 22), date(2026, 7, 23)), (date(2026, 7, 25), date(2026, 7, 26))):
            for employee in (self.employee, coworker):
                VacationScheduleItem.objects.create(
                    schedule=schedule,
                    employee=employee,
                    start_date=start_date,
                    end_date=end_date,
                    vacation_type="paid",
                    chargeable_days=(end_date - start_date).days + 1,
                    status=VacationScheduleItem.STATUS_APPROVED,
                )
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("calendar"), {"view": "month", "year": 2026, "month": 7, "issue": "conflict"})

        detail = response.context["calendar_details"][str(self.employee.id)]
        problems = detail["risk_details"]["problems"]
        self.assertEqual(len(problems), 2)
        self.assertEqual([problem["title"] for problem in problems], ["Группа не проходит по составу", "Группа не проходит по составу"])
        self.assertEqual([problem["period_label"] for problem in problems], ["22-23 июля", "25-26 июля"])
        self.assertTrue(all("Периодов Артем" in problem["affected_names"] for problem in problems))

    def test_calendar_conflict_details_merge_substitution_into_conflict_problem(self):
        DepartmentStaffingRule.objects.create(
            department=self.engineering,
            min_staff_required=0,
            max_absent=10,
            criticality_level=3,
        )
        substitute_group = ProductionGroup.objects.create(department=self.engineering, name="Резерв качества")
        substitute_position = EmployeePosition.objects.create(
            department=self.engineering,
            production_group=substitute_group,
            title="Резервный инженер",
        )
        ProductionGroupSubstitutionRule.objects.create(
            department=self.engineering,
            source_group=self.engineering_group,
            substitute_group=substitute_group,
        )
        DepartmentCoverageRule.objects.create(
            department=self.engineering,
            production_group=self.engineering_group,
            min_staff_required=1,
            max_absent=1,
            criticality_level=5,
        )
        coworker = Employees.objects.create(
            last_name="Замещаемый",
            first_name="Артем",
            middle_name="Иванович",
            login="calendar-merged-substitution-coworker",
            position="Инженер",
            employee_position=self.engineering_engineer_position,
            department=self.engineering,
            date_joined=date(2024, 1, 10),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        Employees.objects.create(
            last_name="Резервный",
            first_name="Петр",
            middle_name="Иванович",
            login="calendar-merged-substitution-reserve",
            position="Резервный инженер",
            employee_position=substitute_position,
            department=self.engineering,
            date_joined=date(2024, 1, 10),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        for employee in (self.employee, coworker):
            VacationScheduleItem.objects.create(
                schedule=schedule,
                employee=employee,
                start_date=date(2026, 7, 22),
                end_date=date(2026, 7, 23),
                vacation_type="paid",
                chargeable_days=2,
                status=VacationScheduleItem.STATUS_APPROVED,
            )
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("calendar"), {"view": "month", "year": 2026, "month": 7, "issue": "conflict"})

        detail = response.context["calendar_details"][str(self.employee.id)]
        problems = detail["risk_details"]["problems"]
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["title"], "Превышен лимит отсутствующих")
        self.assertIn("Замещение покрывает 1 сотрудник", problems[0]["substitution_label"])
        self.assertIn("лимит всё равно превышен на 1 сотрудник", problems[0]["substitution_label"])

    def test_calendar_substitution_prevents_group_shortage_conflict(self):
        DepartmentStaffingRule.objects.create(
            department=self.engineering,
            min_staff_required=0,
            max_absent=10,
            criticality_level=3,
        )
        substitute_group = ProductionGroup.objects.create(department=self.engineering, name="Замещающая группа")
        substitute_position = EmployeePosition.objects.create(
            department=self.engineering,
            production_group=substitute_group,
            title="Сменный специалист",
        )
        ProductionGroupSubstitutionRule.objects.create(
            department=self.engineering,
            source_group=self.engineering_group,
            substitute_group=substitute_group,
        )
        DepartmentCoverageRule.objects.create(
            department=self.engineering,
            production_group=self.engineering_group,
            min_staff_required=1,
            max_absent=5,
            criticality_level=5,
        )
        Employees.objects.create(
            last_name="Замещающий",
            first_name="Петр",
            middle_name="Иванович",
            login="calendar-substitute",
            position="Сменный специалист",
            employee_position=substitute_position,
            department=self.engineering,
            date_joined=date(2024, 1, 10),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 7),
            vacation_type="paid",
            chargeable_days=7,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("calendar"), {"view": "month", "year": 2026, "month": 10, "issue": "conflict"})

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.employee.full_name)

        risk_response = self.client.get(reverse("calendar"), {"view": "month", "year": 2026, "month": 10, "issue": "risk"})

        self.assertContains(risk_response, self.employee.full_name)
        detail = risk_response.context["calendar_details"][str(self.employee.id)]
        self.assertTrue(detail["has_high_risk"])
        self.assertIn("закрыта замещением", detail["risk_summary"])
        self.assertFalse(detail["has_conflict"])
        self.assertEqual(detail["risk_details"]["problems"][0]["title"], "Нужно замещение")
        self.assertIn("Замещение покрывает", detail["risk_details"]["problems"][0]["impact_label"])

    def test_calendar_substitution_respects_capacity_and_free_staff(self):
        DepartmentStaffingRule.objects.create(
            department=self.engineering,
            min_staff_required=0,
            max_absent=10,
            criticality_level=3,
        )
        substitute_group = ProductionGroup.objects.create(department=self.engineering, name="Ограниченная замена")
        substitute_position = EmployeePosition.objects.create(
            department=self.engineering,
            production_group=substitute_group,
            title="Сменный эксперт",
        )
        ProductionGroupSubstitutionRule.objects.create(
            department=self.engineering,
            source_group=self.engineering_group,
            substitute_group=substitute_group,
            max_covered_absences=1,
        )
        DepartmentCoverageRule.objects.create(
            department=self.engineering,
            production_group=self.engineering_group,
            min_staff_required=2,
            max_absent=5,
            criticality_level=5,
        )
        coworker = Employees.objects.create(
            last_name="Группов",
            first_name="Артем",
            middle_name="Иванович",
            login="calendar-capacity-coworker",
            position="Инженер",
            employee_position=self.engineering_engineer_position,
            department=self.engineering,
            date_joined=date(2024, 1, 10),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        Employees.objects.create(
            last_name="Замещающий",
            first_name="Петр",
            middle_name="Иванович",
            login="calendar-capacity-substitute",
            position="Сменный эксперт",
            employee_position=substitute_position,
            department=self.engineering,
            date_joined=date(2024, 1, 10),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        for employee in (self.employee, coworker):
            VacationScheduleItem.objects.create(
                schedule=schedule,
                employee=employee,
                start_date=date(2026, 10, 1),
                end_date=date(2026, 10, 7),
                vacation_type="paid",
                chargeable_days=7,
                status=VacationScheduleItem.STATUS_APPROVED,
            )
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("calendar"), {"view": "month", "year": 2026, "month": 10, "issue": "conflict"})

        self.assertContains(response, self.employee.full_name)
        detail = response.context["calendar_details"][str(self.employee.id)]
        self.assertTrue(detail["has_conflict"])
        self.assertIn("не хватает: Инженеры", detail["conflict_summary"])

    def test_calendar_conflict_detects_department_head_and_deputy_absence(self):
        self.engineering.deputy = self.employee
        self.engineering.save(update_fields=["deputy"])
        DepartmentStaffingRule.objects.create(
            department=self.engineering,
            min_staff_required=0,
            max_absent=10,
            criticality_level=3,
        )
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        for employee in (self.employee, self.department_head):
            VacationScheduleItem.objects.create(
                schedule=schedule,
                employee=employee,
                start_date=date(2026, 11, 1),
                end_date=date(2026, 11, 7),
                vacation_type="paid",
                chargeable_days=7,
                status=VacationScheduleItem.STATUS_APPROVED,
            )
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("calendar"), {"view": "month", "year": 2026, "month": 11, "issue": "conflict"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.employee.full_name)
        detail = response.context["calendar_details"][str(self.employee.id)]
        self.assertIn("руководитель отдела и заместитель отсутствуют", detail["conflict_summary"])

    def test_calendar_ajax_preserves_filter_parameters(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(
            reverse("calendar"),
            {
                "view": "year",
                "year": 2026,
                "department": self.engineering.id,
                "search": self.employee.last_name,
                "issue": "all",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(self.employee.full_name, payload["board_html"])
        self.assertNotIn(self.outsider.full_name, payload["board_html"])

    def test_calendar_year_filter_includes_years_with_schedule_items(self):
        old_employee = Employees.objects.create(
            last_name="Исторический",
            first_name="Иван",
            middle_name="Петрович",
            login="historical-calendar-user",
            position="Специалист",
            department=self.engineering,
            date_joined=date(2014, 1, 10),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        schedule = VacationSchedule.objects.create(
            year=2015,
            status=VacationSchedule.STATUS_ARCHIVED,
            approved_by=self.enterprise_head,
        )
        VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=old_employee,
            start_date=date(2015, 7, 1),
            end_date=date(2015, 7, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("calendar"), {"view": "year", "year": 2015})

        self.assertEqual(response.status_code, 200)
        self.assertIn(2015, response.context["calendar_filters"]["available_years"])
        self.assertEqual(response.context["calendar_filters"]["selected_year"], 2015)

    def test_calendar_rows_include_schedule_items(self):
        old_employee = Employees.objects.create(
            last_name="Архивный",
            first_name="Петр",
            middle_name="Иванович",
            login="archive-calendar-user",
            position="Специалист",
            department=self.engineering,
            date_joined=date(2014, 1, 10),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        schedule = VacationSchedule.objects.create(
            year=2015,
            status=VacationSchedule.STATUS_ARCHIVED,
            approved_by=self.enterprise_head,
        )
        VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=old_employee,
            start_date=date(2015, 7, 1),
            end_date=date(2015, 7, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
        )

        employees, employee_day_status, employee_entries = build_calendar_base_data(2015)
        rows, details = build_calendar_rows(
            employees,
            employee_day_status,
            employee_entries,
            year=2015,
            month=7,
            view_mode="month",
            today=date(2015, 7, 1),
        )

        row = next(row for row in rows if row["employee_id"] == old_employee.id)
        self.assertEqual(row["selected_approved_days"], 14)
        self.assertEqual(row["profile_url"], reverse("employee_profile", args=[old_employee.id]))
        self.assertEqual(row["role_icon"], "person")
        self.assertEqual(row["role_icon_type"], "material")
        self.assertEqual(row["role_variant"], "employee")
        self.assertEqual(row["role_label"], "Сотрудник")
        self.assertEqual(row["selected_schedule_days"], 14)
        self.assertEqual(row["status"], "schedule-approved")
        self.assertEqual(details[str(old_employee.id)]["selected_entries"][0]["status_label"], "График утвержден")
        self.assertEqual(details[str(old_employee.id)]["selected_entries"][0]["source_label"], "Годовой график")
        self.assertEqual(details[str(old_employee.id)]["selected_entries"][0]["detail_url"], "")
        self.assertEqual(details[str(old_employee.id)]["selected_entries"][0]["risk_label"], "Низкий")
        self.assertEqual(details[str(old_employee.id)]["selected_entries"][0]["anchor"]["start_date"], "2015-07-01")
        self.assertEqual(details[str(old_employee.id)]["profile_url"], reverse("employee_profile", args=[old_employee.id]))
        self.assertEqual(details[str(old_employee.id)]["role_icon"], "person")
        self.assertEqual(details[str(old_employee.id)]["role_variant"], "employee")

    def test_calendar_year_view_uses_compact_legend_and_simple_month_cards(self):
        schedule = VacationSchedule.objects.create(
            year=2026,
            status=VacationSchedule.STATUS_APPROVED,
            approved_by=self.enterprise_head,
        )
        VacationScheduleItem.objects.create(
            schedule=schedule,
            employee=self.employee,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 14),
            vacation_type="paid",
            chargeable_days=14,
            status=VacationScheduleItem.STATUS_APPROVED,
        )
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("calendar"), {"view": "year", "year": 2026, "employee": self.employee.id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "calendar-legend-toggle")
        self.assertContains(response, "calendar-legend-popover")
        self.assertContains(response, "calendar-legend__item--schedule-approved")
        self.assertContains(response, "calendar-legend__item--issue-risk")
        self.assertContains(response, "calendar-legend__item--issue-conflict")
        self.assertContains(response, "year-grid--totals")
        self.assertNotContains(response, "year-grid--head")
        self.assertNotContains(response, "year-head--month")
        self.assertContains(response, "Итого")
        self.assertContains(response, "data-calendar-month")
        self.assertContains(response, "bolt")
        self.assertContains(response, "⚔")
        self.assertNotContains(response, "timeline-employee-card__stats")
        self.assertNotContains(response, "year-month-card__stats")
        self.assertContains(response, "data-calendar-focus-entry")
        self.assertContains(response, "data-calendar-focus-upcoming")
        july_total = response.context["calendar_month_totals"][6]
        self.assertEqual(july_total["employee_count"], 1)
        self.assertEqual(july_total["busy_days"], 14)
        detail = response.context["calendar_details"][str(self.employee.id)]
        self.assertEqual(detail["upcoming_anchor"]["employee_id"], self.employee.id)
        self.assertEqual(detail["upcoming_anchor"]["start_date"], "2026-07-01")

    def test_calendar_month_view_does_not_render_year_totals(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("calendar"), {"view": "month", "year": 2026, "month": 7})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["calendar_month_totals"], [])
        self.assertNotContains(response, "year-grid--totals")
        month_html = response.content.decode()
        self.assertIn(
            '<div class="timeline-head timeline-head--employee">\n                <span>Дата</span>\n            </div>',
            month_html,
        )
        self.assertNotIn(
            '<div class="timeline-head timeline-head--employee">\n                <span>Сотрудник</span>\n            </div>',
            month_html,
        )

    def test_calendar_hides_employees_not_hired_by_selected_year_end(self):
        employees, _, _ = build_calendar_base_data(2015)

        self.assertNotIn(self.employee.id, [employee.id for employee in employees])

    def test_calendar_rows_include_rejected_requests_in_month_and_year_views(self):
        rejected_request = VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-05-10",
            end_date="2026-05-12",
            vacation_type="paid",
            status=VacationRequest.STATUS_REJECTED,
        )

        employees, employee_day_status, employee_entries = build_calendar_base_data(2026)
        month_rows, month_details = build_calendar_rows(
            employees,
            employee_day_status,
            employee_entries,
            year=2026,
            month=5,
            view_mode="month",
            today=date(2026, 5, 1),
        )
        year_rows, _ = build_calendar_rows(
            employees,
            employee_day_status,
            employee_entries,
            year=2026,
            month=5,
            view_mode="year",
            today=date(2026, 5, 1),
        )

        month_row = next(row for row in month_rows if row["employee_id"] == self.employee.id)
        year_row = next(row for row in year_rows if row["employee_id"] == self.employee.id)
        may_cell = year_row["cells"][4]

        self.assertEqual(month_row["selected_rejected_days"], 3)
        self.assertEqual(month_row["status"], "request-rejected")
        self.assertEqual(year_row["year_rejected_days"], 3)
        self.assertEqual(may_cell["rejected_days"], 3)
        self.assertEqual(may_cell["status"], "request-rejected")
        self.assertEqual(month_details[str(self.employee.id)]["selected_rejected_days"], 3)
        self.assertEqual(
            month_details[str(self.employee.id)]["selected_entries"][0]["detail_url"],
            reverse("vacation_detail", args=[rejected_request.id]),
        )

    def test_year_view_segments_follow_real_dates_across_month_boundary(self):
        VacationRequest.objects.create(
            employee=self.employee,
            start_date="2026-03-19",
            end_date="2026-04-01",
            vacation_type="paid",
            status=VacationRequest.STATUS_PENDING,
        )

        employees, employee_day_status, employee_entries = build_calendar_base_data(2026)
        rows, _ = build_calendar_rows(
            employees,
            employee_day_status,
            employee_entries,
            year=2026,
            month=3,
            view_mode="year",
            today=date(2026, 3, 1),
        )

        row = next(row for row in rows if row["employee_id"] == self.employee.id)
        march_cell = row["cells"][2]
        april_cell = row["cells"][3]

        self.assertEqual(march_cell["pending_days"], 13)
        self.assertEqual(len(march_cell["segments"]), 1)
        self.assertEqual(march_cell["segments"][0]["offset_percent"], 58.1)
        self.assertEqual(march_cell["segments"][0]["width_percent"], 41.9)
        self.assertEqual(april_cell["pending_days"], 1)
        self.assertEqual(len(april_cell["segments"]), 1)
        self.assertEqual(april_cell["segments"][0]["offset_percent"], 0.0)
        self.assertEqual(april_cell["segments"][0]["width_percent"], 3.3)
