from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator
from django.db import models
from django.utils import timezone


class Employees(models.Model):
    ROLE_EMPLOYEE = "employee"
    ROLE_HR = "hr"
    ROLE_DEPARTMENT_HEAD = "department_head"
    ROLE_ENTERPRISE_HEAD = "enterprise_head"
    ROLE_AUTHORIZED_PERSON = "authorized_person"

    ROLE_CHOICES = [
        (ROLE_EMPLOYEE, "Сотрудник"),
        (ROLE_HR, "HR"),
        (ROLE_DEPARTMENT_HEAD, "Руководитель отдела"),
        (ROLE_ENTERPRISE_HEAD, "Руководитель предприятия"),
        (ROLE_AUTHORIZED_PERSON, "Уполномоченное лицо"),
    ]
    MANAGEMENT_ROLES = {
        ROLE_HR,
        ROLE_DEPARTMENT_HEAD,
        ROLE_ENTERPRISE_HEAD,
    }
    SERVICE_ROLES = {
        ROLE_AUTHORIZED_PERSON,
    }
    EDITABLE_ROLE_CHOICES = [
        (ROLE_EMPLOYEE, "Сотрудник"),
        (ROLE_HR, "HR"),
        (ROLE_DEPARTMENT_HEAD, "Руководитель отдела"),
        (ROLE_ENTERPRISE_HEAD, "Руководитель предприятия"),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_profile",
    )
    last_name = models.CharField(max_length=100, default="", verbose_name="Фамилия")
    first_name = models.CharField(max_length=100, default="", verbose_name="Имя")
    middle_name = models.CharField(max_length=100, default="", verbose_name="Отчество")
    login = models.CharField(max_length=150, unique=True, verbose_name="Логин")
    position = models.CharField(max_length=100, verbose_name="Должность")
    role = models.CharField(
        max_length=32,
        choices=ROLE_CHOICES,
        default=ROLE_EMPLOYEE,
        verbose_name="Роль в системе",
    )
    date_joined = models.DateField(verbose_name="Дата начала работы", default=timezone.now)
    vacation_days = models.PositiveIntegerField(
        verbose_name="Количество отпускных дней",
        default=0,
        validators=[MaxValueValidator(52)],
    )
    annual_paid_leave_days = models.PositiveIntegerField(
        verbose_name="Годовая норма оплачиваемого отпуска",
        default=52,
        validators=[MaxValueValidator(52)],
    )
    manual_leave_adjustment_days = models.IntegerField(
        verbose_name="Ручная корректировка отпускного баланса",
        default=0,
    )
    used_up_days = models.PositiveIntegerField(
        verbose_name="Использованные дни",
        default=0,
        validators=[MaxValueValidator(3650)],
    )
    is_active_employee = models.BooleanField(default=True, verbose_name="Активный сотрудник")
    is_working = models.BooleanField(default=True, verbose_name="Работает")
    department = models.ForeignKey(
        to="employees.Departments",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Отдел",
        related_name="employees",
    )
    password = models.CharField(
        max_length=128,
        verbose_name="Служебный пароль (legacy)",
        default="",
        blank=True,
    )
    is_manager = models.BooleanField(default=False, verbose_name="Руководитель")

    class Meta:
        db_table = "employees_employees"
        verbose_name = "Сотрудник"
        verbose_name_plural = "Сотрудники"

    @property
    def full_name(self):
        return " ".join(part for part in [self.last_name, self.first_name, self.middle_name] if part).strip()

    @property
    def is_management(self):
        return self.role in self.MANAGEMENT_ROLES

    @property
    def is_service_account(self):
        return self.role in self.SERVICE_ROLES

    def save(self, *args, **kwargs):
        if self.is_service_account:
            self.last_name = ""
            self.first_name = ""
            self.middle_name = ""
            self.position = ""
            self.department = None
            self.annual_paid_leave_days = 0
            self.vacation_days = 0
            self.used_up_days = 0
            self.is_working = False
        self.is_manager = self.is_management
        super().save(*args, **kwargs)

    def __str__(self):
        return self.full_name or self.login


class Departments(models.Model):
    name = models.CharField(max_length=150, unique=True, verbose_name="Название отдела")
    head = models.OneToOneField(
        to="employees.Employees",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_department",
        verbose_name="Руководитель отдела",
    )
    date_added = models.DateTimeField(default=timezone.now, verbose_name="Дата добавления")

    class Meta:
        db_table = "employees_departments"
        verbose_name = "Отдел"
        verbose_name_plural = "Отделы"

    def __str__(self):
        return self.name
