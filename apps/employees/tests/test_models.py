from .base import EmployeeTestCase


class EmployeeModelTests(EmployeeTestCase):
    def test_employee_full_name_property(self):
        self.assertEqual(self.employee.full_name, "Сотрудник Иван Игоревич")

    def test_department_head_is_linked_to_department(self):
        self.engineering.refresh_from_db()
        self.assertEqual(self.engineering.head, self.department_head)
