from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator
from django.db import models
from django.utils import timezone


class Departments(models.Model):
    name = models.CharField(max_length=150, unique=True, verbose_name='Название отдела')
    date_added = models.DateTimeField(default=timezone.now, verbose_name='Дата добавления')

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = 'Отдел'
        verbose_name_plural = 'Отделы'


class Employees(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employee_profile',
    )
    name = models.CharField(max_length=100, verbose_name='ФИО')
    position = models.CharField(max_length=100, verbose_name='Должность')
    date_joined = models.DateField(verbose_name='Дата начала работы', default=timezone.now)
    vacation_days = models.PositiveIntegerField(
        verbose_name='Количество отпускных дней',
        default=0,
        validators=[MaxValueValidator(52)],
    )
    used_up_days = models.PositiveIntegerField(
        verbose_name='Использованные дни',
        default=0,
        validators=[MaxValueValidator(52)],
    )
    is_working = models.BooleanField(default=True, verbose_name='Работает')
    department = models.ForeignKey(
        to='Departments',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Отдел',
    )
    password = models.CharField(max_length=128, verbose_name='Пароль')
    is_manager = models.BooleanField(default=False, verbose_name='Руководитель')

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = 'Сотрудник'
        verbose_name_plural = 'Сотрудники'


VACATION_TYPE_CHOICES = [
    ('paid', 'Оплачиваемый'),
    ('unpaid', 'Неоплачиваемый'),
    ('study', 'Учебный'),
]


class VacationRequest(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'В ожидании'),
        (STATUS_APPROVED, 'Одобрено'),
        (STATUS_REJECTED, 'Отклонено'),
    ]

    employee = models.ForeignKey(
        to='Employees',
        on_delete=models.CASCADE,
        related_name='vacation_requests',
        verbose_name='Сотрудник',
    )
    start_date = models.DateField(verbose_name='Дата начала')
    end_date = models.DateField(verbose_name='Дата окончания')
    vacation_type = models.CharField(
        max_length=50,
        choices=VACATION_TYPE_CHOICES,
        default='paid',
        verbose_name='Тип отпуска',
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        verbose_name='Статус',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')

    def __str__(self):
        return f'Заявка {self.employee.name}: {self.get_status_display()} с {self.start_date} по {self.end_date}'

    class Meta:
        verbose_name = 'Заявка на отпуск'
        verbose_name_plural = 'Заявки на отпуск'
        ordering = ['-created_at']


# Совместимость со старым кодом во время перехода на единую модель заявок.
Vacation = VacationRequest
PreHolidays = VacationRequest
CanceledHolidays = VacationRequest
СanceledHolidays = VacationRequest
