from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator
from django.db import models
from django.utils import timezone


class Departments(models.Model):
    name = models.CharField(max_length=150, unique=True, verbose_name="Название отдела")
    date_added = models.DateTimeField(default=timezone.now, verbose_name="Дата добавления")

    class Meta:
        db_table = "employees_departments"
        verbose_name = "Отдел"
        verbose_name_plural = "Отделы"

    def __str__(self):
        return self.name


class Employees(models.Model):
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
    date_joined = models.DateField(verbose_name="Дата начала работы", default=timezone.now)
    vacation_days = models.PositiveIntegerField(
        verbose_name="Количество отпускных дней",
        default=0,
        validators=[MaxValueValidator(52)],
    )
    used_up_days = models.PositiveIntegerField(
        verbose_name="Использованные дни",
        default=0,
        validators=[MaxValueValidator(52)],
    )
    is_working = models.BooleanField(default=True, verbose_name="Работает")
    department = models.ForeignKey(
        to="employees.Departments",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Отдел",
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

    def __str__(self):
        return self.full_name
