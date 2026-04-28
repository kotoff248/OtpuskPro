from apps.employees.forms import EmployeeCreateForm
from apps.employees.models import Employees

from .base import EmployeeTestCase


class EmployeeFormTests(EmployeeTestCase):
    def test_duplicate_login_is_rejected(self):
        form = EmployeeCreateForm(
            data={
                "login": "employee-login",
                "last_name": "Новый",
                "first_name": "Сотрудник",
                "middle_name": "Андреевич",
                "position": "Аналитик",
                "date_joined": "2026-01-01",
                "annual_paid_leave_days": 52,
                "department": self.engineering.id,
                "role": Employees.ROLE_EMPLOYEE,
                "password": "new-user-pass",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("login", form.errors)

    def test_employee_form_does_not_offer_authorized_person_role(self):
        form = EmployeeCreateForm()

        role_values = {value for value, _label in form.fields["role"].choices}

        self.assertNotIn(Employees.ROLE_AUTHORIZED_PERSON, role_values)
