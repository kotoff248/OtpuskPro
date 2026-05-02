from django.urls import reverse

from apps.employees.models import (
    DepartmentCoverageRule,
    Departments,
    EmployeePosition,
    ProductionGroup,
    ProductionGroupSubstitutionRule,
)

from .base import EmployeeTestCase


class StaffingRulesPageTests(EmployeeTestCase):
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

    def test_department_head_sees_only_own_department_without_editing(self):
        self.client.force_login(self.department_head.user)

        response = self.client.get(reverse("staffing_rules"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_edit_staffing"])
        self.assertContains(response, self.engineering.name)
        self.assertNotContains(response, self.hr_department.name)
        self.assertNotContains(response, 'name="action" value="create_group"')
        self.assertNotContains(response, 'name="action" value="delete_department"')

        post_response = self.client.post(
            reverse("staffing_rules"),
            {
                "action": "delete_department",
                "department_id": self.engineering.id,
            },
        )

        self.assertRedirects(post_response, reverse("staffing_rules"))
        self.assertTrue(Departments.objects.filter(id=self.engineering.id).exists())

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
