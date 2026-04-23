from django import forms
from django.contrib.auth import get_user_model

from apps.accounts.services import normalize_employee_login, sync_employee_user
from apps.employees.models import Departments, Employees


class EmployeeBaseForm(forms.ModelForm):
    login = forms.CharField(max_length=150, label="Логин")
    date_joined = forms.DateField(
        label="Дата начала работы",
        input_formats=[
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%d %H:%M:%S",
        ],
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    password = forms.CharField(
        required=False,
        label="Пароль",
        strip=False,
        widget=forms.PasswordInput(render_value=False),
    )
    annual_paid_leave_days = forms.IntegerField(
        min_value=0,
        max_value=52,
        initial=52,
        label="Годовая норма оплачиваемого отпуска",
    )
    role = forms.ChoiceField(choices=Employees.ROLE_CHOICES, label="Роль в системе")

    class Meta:
        model = Employees
        fields = [
            "login",
            "last_name",
            "first_name",
            "middle_name",
            "position",
            "role",
            "date_joined",
            "annual_paid_leave_days",
            "department",
        ]

    def _clean_name_part(self, field_name, error_message):
        value = (self.cleaned_data.get(field_name) or "").strip()
        if not value:
            raise forms.ValidationError(error_message)
        return value

    def clean_login(self):
        login_value = normalize_employee_login(self.cleaned_data["login"])
        if not login_value:
            raise forms.ValidationError("Введите логин сотрудника.")

        employees_qs = Employees.objects.exclude(pk=self.instance.pk).filter(login__iexact=login_value)
        if employees_qs.exists():
            raise forms.ValidationError("Сотрудник с таким логином уже существует.")

        user_qs = get_user_model().objects.exclude(pk=getattr(self.instance, "user_id", None)).filter(
            username__iexact=login_value
        )
        if user_qs.exists():
            raise forms.ValidationError("Этот логин уже занят.")

        return login_value

    def clean_last_name(self):
        return self._clean_name_part("last_name", "Введите фамилию сотрудника.")

    def clean_first_name(self):
        return self._clean_name_part("first_name", "Введите имя сотрудника.")

    def clean_middle_name(self):
        return self._clean_name_part("middle_name", "Введите отчество сотрудника.")

    def clean_position(self):
        value = (self.cleaned_data.get("position") or "").strip()
        if not value:
            raise forms.ValidationError("Введите должность сотрудника.")
        return value

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get("role")
        department = cleaned_data.get("department")

        if role == Employees.ROLE_DEPARTMENT_HEAD and department is None:
            self.add_error("department", "Для руководителя отдела нужно выбрать отдел.")
            return cleaned_data

        if role == Employees.ROLE_DEPARTMENT_HEAD and department is not None:
            occupied_department = Departments.objects.exclude(head=self.instance).filter(pk=department.pk, head__isnull=False).first()
            if occupied_department is not None:
                self.add_error("department", "У отдела уже назначен другой руководитель.")

        return cleaned_data

    def save(self, commit=True):
        employee = super().save(commit=False)
        employee.vacation_days = employee.annual_paid_leave_days
        if commit:
            employee.save()
            sync_employee_user(employee, raw_password=self.cleaned_data.get("password") or None)
        return employee


class EmployeeCreateForm(EmployeeBaseForm):
    password = forms.CharField(
        required=True,
        label="Пароль",
        strip=False,
        widget=forms.PasswordInput(render_value=False),
    )


class EmployeeUpdateForm(EmployeeBaseForm):
    password = forms.CharField(
        required=False,
        label="Новый пароль",
        strip=False,
        widget=forms.PasswordInput(render_value=False),
    )
