from unittest.mock import patch

from django.contrib.auth import SESSION_KEY
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.employees.models import (
    DepartmentCoverageRule,
    Departments,
    EmployeePosition,
    ProductionGroup,
    ProductionGroupSubstitutionRule,
)
from apps.leave.models import DepartmentStaffingRule, DepartmentWorkload

from .base import EmployeeTestCase


class StaffingRulesPageTests(EmployeeTestCase):
    def _workload_payload(self, action="save_workload_year", year=2026):
        payload = {
            "action": action,
            "department_id": self.engineering.id,
            "year": year,
        }
        for month in range(1, 13):
            payload[f"load_level_{month}"] = 2
            payload[f"min_staff_required_{month}"] = 1
            payload[f"max_absent_{month}"] = 1
        return payload

    def test_hr_can_open_and_edit_staffing_rules(self):
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("staffing_rules"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Правила состава")
        self.assertTrue(response.context["can_edit_staffing"])
        self.assertContains(response, self.engineering.name)
        self.assertContains(response, self.hr_department.name)
        self.assertContains(response, 'data-modal-open="staffing-delete-department-')
        self.assertContains(response, "Действительно ли вы хотите удалить отдел?")
        self.assertContains(response, 'name="action" value="delete_department"')
        self.assertContains(response, "Месячные лимиты")
        self.assertContains(response, 'name="action" value="save_workload_year"')
        self.assertNotContains(response, 'value="fill_workload_year"')
        self.assertContains(response, "data-staffing-workload-year-select")
        self.assertContains(response, "Лимит отсутствий")
        self.assertNotContains(response, ">Нагр.<")
        self.assertNotContains(response, ">Мин.<")
        self.assertNotContains(response, ">Отс.<")
        self.assertNotContains(response, ">Показать<")

        post_response = self.client.post(
            reverse("staffing_rules"),
            {
                "action": "create_group",
                "department_id": self.engineering.id,
                "name": "Диспетчеры",
                "code": "dispatch",
            },
        )

        self.assertRedirects(post_response, reverse("staffing_rules"))
        self.assertTrue(ProductionGroup.objects.filter(department=self.engineering, name="Диспетчеры").exists())

    def test_staffing_page_explains_rule_quality(self):
        self.client.force_login(self.hr_employee.user)
        empty_substitute_group = ProductionGroup.objects.create(department=self.engineering, name="Пустой резерв")
        DepartmentCoverageRule.objects.create(
            department=self.engineering,
            production_group=self.engineering_group,
            min_staff_required=2,
            max_absent=3,
            criticality_level=5,
        )
        ProductionGroupSubstitutionRule.objects.create(
            department=self.engineering,
            source_group=self.engineering_group,
            substitute_group=empty_substitute_group,
            max_covered_absences=2,
        )

        response = self.client.get(reverse("staffing_rules"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Качество правил отдела")
        self.assertContains(response, "Риск состава:")
        self.assertContains(response, "Слишком жёстко")
        self.assertContains(response, "Нет замещающих")
        self.assertContains(response, "Резерв:")
        self.assertContains(response, "staffing-diagnostic-chip")
        self.assertContains(response, "staffing-workload-month__quality")
        self.assertContains(response, "data-schedule-status-tooltip")
        self.assertContains(response, 'data-tooltip-title="Риск состава"')
        self.assertContains(response, 'data-tooltip-title="Критичность"')
        self.assertContains(response, 'data-tooltip-title="Нагрузка месяца"')
        self.assertContains(response, "staffing-workload-month__label")
        self.assertContains(response, "beach_access")

    def test_staffing_deputy_picker_marks_new_hires(self):
        self.employee.date_joined = timezone.localdate()
        self.employee.save(update_fields=["date_joined"])
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("staffing_rules"))

        self.assertEqual(response.status_code, 200)
        active_employees = {employee.id: employee for employee in response.context["enterprise_deputy_candidates"]}
        self.assertEqual(active_employees[self.employee.id].new_hire_badge["label"], "Новичок")
        self.assertContains(response, 'class="new-hire-badge"')
        self.assertContains(response, "person_add")
        self.assertContains(response, "Работает меньше 6 месяцев")

    @override_settings(DEBUG=True)
    def test_enterprise_head_sees_demo_reset_button_in_debug(self):
        self.client.force_login(self.enterprise_head.user)

        response = self.client.get(reverse("staffing_rules"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["can_reset_demo_data"])
        self.assertContains(response, "Пересоздать демо-данные")
        self.assertContains(response, 'data-modal-open="staffing-demo-reset-modal"')
        self.assertContains(response, reverse("reset_demo_data"))

    @override_settings(DEBUG=True)
    def test_demo_reset_button_is_hidden_from_hr_and_department_head(self):
        self.client.force_login(self.hr_employee.user)
        hr_response = self.client.get(reverse("staffing_rules"))
        self.assertFalse(hr_response.context["can_reset_demo_data"])
        self.assertNotContains(hr_response, 'data-modal-open="staffing-demo-reset-modal"')

        self.client.force_login(self.department_head.user)
        head_response = self.client.get(reverse("staffing_rules"))
        self.assertFalse(head_response.context["can_reset_demo_data"])
        self.assertNotContains(head_response, 'data-modal-open="staffing-demo-reset-modal"')

    @override_settings(DEBUG=False)
    def test_demo_reset_button_is_hidden_outside_debug(self):
        self.client.force_login(self.enterprise_head.user)

        response = self.client.get(reverse("staffing_rules"))

        self.assertFalse(response.context["can_reset_demo_data"])
        self.assertNotContains(response, 'data-modal-open="staffing-demo-reset-modal"')

    @override_settings(DEBUG=True)
    @patch("apps.employees.views.call_command")
    @patch("apps.employees.views.secrets.randbelow", return_value=123455)
    def test_enterprise_head_can_reset_demo_data_and_is_logged_out(self, randbelow_mock, call_command_mock):
        self.client.force_login(self.enterprise_head.user)

        response = self.client.post(reverse("reset_demo_data"), follow=True)

        self.assertRedirects(response, reverse("login"))
        call_command_mock.assert_called_once()
        command_name = call_command_mock.call_args.args[0]
        command_kwargs = call_command_mock.call_args.kwargs
        self.assertEqual(command_name, "seed_vacation_requests")
        self.assertTrue(command_kwargs["confirm_reset"])
        self.assertEqual(command_kwargs["seed_value"], 123456)
        self.assertNotIn("fast", command_kwargs)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertContains(response, "Демо-данные пересозданы")
        self.assertContains(response, "1234")
        randbelow_mock.assert_called_once()

    @override_settings(DEBUG=True)
    @patch("apps.employees.views.call_command")
    def test_demo_reset_post_is_denied_for_other_roles(self, call_command_mock):
        self.client.force_login(self.hr_employee.user)
        hr_response = self.client.post(reverse("reset_demo_data"))
        self.assertRedirects(hr_response, reverse("staffing_rules"))

        self.client.force_login(self.department_head.user)
        head_response = self.client.post(reverse("reset_demo_data"))
        self.assertRedirects(head_response, reverse("staffing_rules"))

        self.client.force_login(self.employee.user)
        employee_response = self.client.post(reverse("reset_demo_data"))
        self.assertRedirects(employee_response, reverse("main"))
        call_command_mock.assert_not_called()

    def test_hr_sees_staffing_item_edit_and_delete_modals(self):
        self.client.force_login(self.hr_employee.user)
        coverage = DepartmentCoverageRule.objects.create(
            department=self.engineering,
            production_group=self.engineering_group,
            min_staff_required=1,
            max_absent=1,
            criticality_level=3,
        )
        substitution = ProductionGroupSubstitutionRule.objects.create(
            department=self.engineering,
            source_group=self.engineering_group,
            substitute_group=self.engineering_leadership_group,
            max_covered_absences=1,
        )

        response = self.client.get(reverse("staffing_rules"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-modal-open="staffing-edit-group-{self.engineering_group.id}-modal"')
        self.assertContains(response, f'data-modal-open="staffing-delete-group-{self.engineering_group.id}-modal"')
        self.assertContains(response, f'data-modal-open="staffing-edit-position-{self.engineering_position.id}-modal"')
        self.assertContains(response, f'data-modal-open="staffing-delete-position-{self.engineering_position.id}-modal"')
        self.assertContains(response, f'data-modal-open="staffing-edit-coverage-{coverage.id}-modal"')
        self.assertContains(response, f'data-modal-open="staffing-delete-coverage-{coverage.id}-modal"')
        self.assertContains(response, f'data-modal-open="staffing-edit-substitution-{substitution.id}-modal"')
        self.assertContains(response, f'data-modal-open="staffing-delete-substitution-{substitution.id}-modal"')
        self.assertContains(response, 'name="action" value="update_group"')
        self.assertContains(response, 'name="action" value="delete_group"')
        self.assertContains(response, 'name="action" value="update_position"')
        self.assertContains(response, 'name="action" value="delete_position"')
        self.assertContains(response, 'name="action" value="update_coverage"')
        self.assertContains(response, 'name="action" value="delete_coverage"')
        self.assertContains(response, "Удалить правило замещения?")

    def test_department_head_sees_only_own_department_without_editing(self):
        self.client.force_login(self.department_head.user)

        response = self.client.get(reverse("staffing_rules"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_edit_staffing"])
        self.assertContains(response, self.engineering.name)
        self.assertNotContains(response, self.hr_department.name)
        self.assertNotContains(response, 'name="action" value="create_group"')
        self.assertNotContains(response, 'name="action" value="delete_department"')
        self.assertNotContains(response, 'name="action" value="update_group"')
        self.assertNotContains(response, 'name="action" value="delete_group"')
        self.assertNotContains(response, 'name="action" value="update_position"')
        self.assertNotContains(response, 'name="action" value="delete_position"')
        self.assertContains(response, "Месячные лимиты")
        self.assertNotContains(response, 'name="action" value="save_workload_year"')

        post_response = self.client.post(
            reverse("staffing_rules"),
            {
                "action": "delete_department",
                "department_id": self.engineering.id,
            },
        )

        self.assertRedirects(post_response, reverse("staffing_rules"))
        self.assertTrue(Departments.objects.filter(id=self.engineering.id).exists())

        group_update_response = self.client.post(
            reverse("staffing_rules"),
            {
                "action": "update_group",
                "department_id": self.engineering.id,
                "group_id": self.engineering_group.id,
                "name": "Нельзя менять",
                "code": "blocked",
            },
        )

        self.assertRedirects(group_update_response, reverse("staffing_rules"))
        self.engineering_group.refresh_from_db()
        self.assertEqual(self.engineering_group.name, "Инженеры")

    def test_staffing_page_saves_department_workload_year(self):
        self.client.force_login(self.hr_employee.user)
        payload = self._workload_payload(year=2026)
        payload.update(
            {
                "load_level_3": 5,
                "min_staff_required_3": 7,
                "max_absent_3": 2,
            }
        )

        response = self.client.post(reverse("staffing_rules"), payload)

        self.assertRedirects(response, f"{reverse('staffing_rules')}?year=2026")
        self.assertEqual(DepartmentWorkload.objects.filter(department=self.engineering, year=2026).count(), 12)
        march_workload = DepartmentWorkload.objects.get(department=self.engineering, year=2026, month=3)
        self.assertEqual(march_workload.load_level, 5)
        self.assertEqual(march_workload.min_staff_required, 7)
        self.assertEqual(march_workload.max_absent, 2)

    def test_staffing_page_inherits_workload_for_year_without_records(self):
        self.client.force_login(self.hr_employee.user)
        DepartmentWorkload.objects.create(
            department=self.engineering,
            year=2026,
            month=1,
            load_level=4,
            min_staff_required=3,
            max_absent=2,
        )

        response = self.client.get(reverse("staffing_rules"), {"year": 2027})

        self.assertEqual(response.status_code, 200)
        department = next(
            department
            for department in response.context["staffing_departments"]
            if department.id == self.engineering.id
        )
        january = department.staffing_workload_months[0]
        self.assertEqual(january["load_level"], 4)
        self.assertEqual(january["min_staff_required"], 3)
        self.assertEqual(january["max_absent"], 2)
        self.assertTrue(january["is_inherited"])
        self.assertFalse(january["is_configured"])

    def test_staffing_page_fills_workload_year_from_department_rule(self):
        self.client.force_login(self.hr_employee.user)
        DepartmentStaffingRule.objects.create(
            department=self.engineering,
            min_staff_required=4,
            max_absent=2,
            criticality_level=3,
        )

        response = self.client.post(
            reverse("staffing_rules"),
            {
                "action": "fill_workload_year",
                "department_id": self.engineering.id,
                "year": 2027,
            },
        )

        self.assertRedirects(response, f"{reverse('staffing_rules')}?year=2027")
        self.assertEqual(DepartmentWorkload.objects.filter(department=self.engineering, year=2027).count(), 12)
        january_workload = DepartmentWorkload.objects.get(department=self.engineering, year=2027, month=1)
        self.assertEqual(january_workload.load_level, 3)
        self.assertEqual(january_workload.min_staff_required, 4)
        self.assertEqual(january_workload.max_absent, 2)

    def test_department_head_cannot_edit_department_workload(self):
        self.client.force_login(self.department_head.user)

        response = self.client.post(reverse("staffing_rules"), self._workload_payload(year=2026))

        self.assertRedirects(response, f"{reverse('staffing_rules')}?year=2026")
        self.assertFalse(DepartmentWorkload.objects.filter(department=self.engineering, year=2026).exists())

    def test_staffing_page_deletes_department_and_unlinks_staff(self):
        self.client.force_login(self.hr_employee.user)
        department_id = self.engineering.id

        delete_response = self.client.post(
            reverse("staffing_rules"),
            {
                "action": "delete_department",
                "department_id": department_id,
            },
        )

        self.assertRedirects(delete_response, reverse("staffing_rules"))
        self.assertFalse(Departments.objects.filter(id=department_id).exists())
        self.assertFalse(ProductionGroup.objects.filter(department_id=department_id).exists())
        self.assertFalse(EmployeePosition.objects.filter(department_id=department_id).exists())

        self.employee.refresh_from_db()
        self.department_head.refresh_from_db()
        self.assertIsNone(self.employee.department_id)
        self.assertIsNone(self.employee.employee_position_id)
        self.assertIsNone(self.department_head.department_id)
        self.assertIsNone(self.department_head.employee_position_id)

    def test_staffing_page_saves_position_and_coverage_rule(self):
        self.client.force_login(self.hr_employee.user)
        group = ProductionGroup.objects.create(department=self.engineering, name="Контроль качества")

        position_response = self.client.post(
            reverse("staffing_rules"),
            {
                "action": "create_position",
                "department_id": self.engineering.id,
                "production_group_id": group.id,
                "title": "Контролер качества",
            },
        )
        self.assertRedirects(position_response, reverse("staffing_rules"))
        self.assertTrue(
            EmployeePosition.objects.filter(
                department=self.engineering,
                production_group=group,
                title="Контролер качества",
            ).exists()
        )

        rule_response = self.client.post(
            reverse("staffing_rules"),
            {
                "action": "save_coverage",
                "department_id": self.engineering.id,
                "production_group_id": group.id,
                "min_staff_required": 2,
                "max_absent": 1,
                "criticality_level": 5,
            },
        )
        self.assertRedirects(rule_response, reverse("staffing_rules"))
        rule = DepartmentCoverageRule.objects.get(department=self.engineering, production_group=group)
        self.assertEqual(rule.min_staff_required, 2)
        self.assertEqual(rule.max_absent, 1)
        self.assertEqual(rule.criticality_level, 5)

    def test_staffing_page_updates_group_position_coverage_and_substitution(self):
        self.client.force_login(self.hr_employee.user)
        target_group = ProductionGroup.objects.create(department=self.engineering, name="Резервная группа")
        coverage = DepartmentCoverageRule.objects.create(
            department=self.engineering,
            production_group=self.engineering_group,
            min_staff_required=1,
            max_absent=1,
            criticality_level=2,
        )
        substitution = ProductionGroupSubstitutionRule.objects.create(
            department=self.engineering,
            source_group=self.engineering_group,
            substitute_group=self.engineering_leadership_group,
            max_covered_absences=1,
        )

        group_response = self.client.post(
            reverse("staffing_rules"),
            {
                "action": "update_group",
                "department_id": self.engineering.id,
                "group_id": self.engineering_group.id,
                "name": "Инженерный резерв",
                "code": "eng-reserve",
            },
        )
        self.assertRedirects(group_response, reverse("staffing_rules"))
        self.engineering_group.refresh_from_db()
        self.assertEqual(self.engineering_group.name, "Инженерный резерв")
        self.assertEqual(self.engineering_group.code, "eng-reserve")

        position_response = self.client.post(
            reverse("staffing_rules"),
            {
                "action": "update_position",
                "department_id": self.engineering.id,
                "position_id": self.engineering_position.id,
                "production_group_id": target_group.id,
                "title": "Старший специалист",
            },
        )
        self.assertRedirects(position_response, reverse("staffing_rules"))
        self.engineering_position.refresh_from_db()
        self.assertEqual(self.engineering_position.title, "Старший специалист")
        self.assertEqual(self.engineering_position.production_group_id, target_group.id)

        coverage_response = self.client.post(
            reverse("staffing_rules"),
            {
                "action": "update_coverage",
                "department_id": self.engineering.id,
                "coverage_id": coverage.id,
                "production_group_id": target_group.id,
                "min_staff_required": 2,
                "max_absent": 1,
                "criticality_level": 5,
            },
        )
        self.assertRedirects(coverage_response, reverse("staffing_rules"))
        coverage.refresh_from_db()
        self.assertEqual(coverage.production_group_id, target_group.id)
        self.assertEqual(coverage.min_staff_required, 2)
        self.assertEqual(coverage.max_absent, 1)
        self.assertEqual(coverage.criticality_level, 5)

        substitution_response = self.client.post(
            reverse("staffing_rules"),
            {
                "action": "update_substitution",
                "department_id": self.engineering.id,
                "substitution_id": substitution.id,
                "source_group_id": self.engineering_leadership_group.id,
                "substitute_group_id": target_group.id,
                "max_covered_absences": 3,
            },
        )
        self.assertRedirects(substitution_response, reverse("staffing_rules"))
        substitution.refresh_from_db()
        self.assertEqual(substitution.source_group_id, self.engineering_leadership_group.id)
        self.assertEqual(substitution.substitute_group_id, target_group.id)
        self.assertEqual(substitution.max_covered_absences, 3)

    def test_staffing_page_deletes_free_position_coverage_and_substitution(self):
        self.client.force_login(self.hr_employee.user)
        source_group = ProductionGroup.objects.create(department=self.engineering, name="Свободный источник")
        substitute_group = ProductionGroup.objects.create(department=self.engineering, name="Свободный резерв")
        position = EmployeePosition.objects.create(
            department=self.engineering,
            production_group=source_group,
            title="Свободная должность",
        )
        coverage = DepartmentCoverageRule.objects.create(
            department=self.engineering,
            production_group=source_group,
            min_staff_required=1,
            max_absent=1,
            criticality_level=3,
        )
        substitution = ProductionGroupSubstitutionRule.objects.create(
            department=self.engineering,
            source_group=source_group,
            substitute_group=substitute_group,
            max_covered_absences=1,
        )

        position_response = self.client.post(
            reverse("staffing_rules"),
            {
                "action": "delete_position",
                "department_id": self.engineering.id,
                "position_id": position.id,
            },
        )
        self.assertRedirects(position_response, reverse("staffing_rules"))
        self.assertFalse(EmployeePosition.objects.filter(id=position.id).exists())

        coverage_response = self.client.post(
            reverse("staffing_rules"),
            {
                "action": "delete_coverage",
                "department_id": self.engineering.id,
                "coverage_id": coverage.id,
            },
        )
        self.assertRedirects(coverage_response, reverse("staffing_rules"))
        self.assertFalse(DepartmentCoverageRule.objects.filter(id=coverage.id).exists())

        substitution_response = self.client.post(
            reverse("staffing_rules"),
            {
                "action": "delete_substitution",
                "department_id": self.engineering.id,
                "substitution_id": substitution.id,
            },
        )
        self.assertRedirects(substitution_response, reverse("staffing_rules"))
        self.assertFalse(ProductionGroupSubstitutionRule.objects.filter(id=substitution.id).exists())

    def test_staffing_page_blocks_deleting_used_group_and_position(self):
        self.client.force_login(self.hr_employee.user)

        group_response = self.client.post(
            reverse("staffing_rules"),
            {
                "action": "delete_group",
                "department_id": self.engineering.id,
                "group_id": self.engineering_group.id,
            },
        )
        self.assertRedirects(group_response, reverse("staffing_rules"))
        self.assertTrue(ProductionGroup.objects.filter(id=self.engineering_group.id).exists())

        position_response = self.client.post(
            reverse("staffing_rules"),
            {
                "action": "delete_position",
                "department_id": self.engineering.id,
                "position_id": self.engineering_position.id,
            },
        )
        self.assertRedirects(position_response, reverse("staffing_rules"))
        self.assertTrue(EmployeePosition.objects.filter(id=self.engineering_position.id).exists())

    def test_staffing_page_saves_and_deletes_substitution_capacity(self):
        self.client.force_login(self.hr_employee.user)
        source_group = ProductionGroup.objects.create(department=self.engineering, name="Диспетчеры")
        substitute_group = ProductionGroup.objects.create(department=self.engineering, name="Старшие логисты")

        create_response = self.client.post(
            reverse("staffing_rules"),
            {
                "action": "create_substitution",
                "department_id": self.engineering.id,
                "source_group_id": source_group.id,
                "substitute_group_id": substitute_group.id,
                "max_covered_absences": 2,
            },
        )

        self.assertRedirects(create_response, reverse("staffing_rules"))
        substitution = ProductionGroupSubstitutionRule.objects.get(
            department=self.engineering,
            source_group=source_group,
            substitute_group=substitute_group,
        )
        self.assertEqual(substitution.max_covered_absences, 2)

        update_response = self.client.post(
            reverse("staffing_rules"),
            {
                "action": "update_substitution",
                "department_id": self.engineering.id,
                "substitution_id": substitution.id,
                "max_covered_absences": 1,
            },
        )

        self.assertRedirects(update_response, reverse("staffing_rules"))
        substitution.refresh_from_db()
        self.assertEqual(substitution.max_covered_absences, 1)

        delete_response = self.client.post(
            reverse("staffing_rules"),
            {
                "action": "delete_substitution",
                "department_id": self.engineering.id,
                "substitution_id": substitution.id,
            },
        )

        self.assertRedirects(delete_response, reverse("staffing_rules"))
        self.assertFalse(ProductionGroupSubstitutionRule.objects.filter(id=substitution.id).exists())
