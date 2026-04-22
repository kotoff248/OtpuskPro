from django.db import models


VACATION_TYPE_CHOICES = [
    ("paid", "Оплачиваемый"),
    ("unpaid", "Неоплачиваемый"),
    ("study", "Учебный"),
]


class VacationRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_PENDING, "В ожидании"),
        (STATUS_APPROVED, "Одобрено"),
        (STATUS_REJECTED, "Отклонено"),
    ]
    ACTIVE_STATUSES = (STATUS_PENDING, STATUS_APPROVED)

    employee = models.ForeignKey(
        to="employees.Employees",
        on_delete=models.CASCADE,
        related_name="vacation_requests",
        verbose_name="Сотрудник",
    )
    start_date = models.DateField(verbose_name="Дата начала")
    end_date = models.DateField(verbose_name="Дата окончания")
    vacation_type = models.CharField(
        max_length=50,
        choices=VACATION_TYPE_CHOICES,
        default="paid",
        verbose_name="Тип отпуска",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        verbose_name="Статус",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    class Meta:
        db_table = "leave_vacationrequest"
        verbose_name = "Заявка на отпуск"
        verbose_name_plural = "Заявки на отпуск"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Заявка {self.employee.full_name}: {self.get_status_display()} с {self.start_date} по {self.end_date}"
