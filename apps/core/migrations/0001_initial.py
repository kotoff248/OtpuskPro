import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("employees", "0010_remove_employees_is_working_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("vacation_request_created", "Создана заявка на отпуск"),
                            ("vacation_request_approved", "Заявка на отпуск одобрена"),
                            ("vacation_request_rejected", "Заявка на отпуск отклонена"),
                            ("schedule_change_created", "Создан запрос переноса"),
                            ("schedule_change_approved", "Перенос одобрен"),
                            ("schedule_change_rejected", "Перенос отклонён"),
                            ("preferences_collection_started", "Начат сбор пожеланий"),
                            ("schedule_review_requested", "Запрошено согласование графика"),
                        ],
                        max_length=64,
                        verbose_name="Тип события",
                    ),
                ),
                ("title", models.CharField(max_length=180, verbose_name="Заголовок")),
                ("message", models.TextField(verbose_name="Текст")),
                ("action_url", models.CharField(blank=True, default="", max_length=255, verbose_name="Ссылка действия")),
                (
                    "status",
                    models.CharField(
                        choices=[("new", "Новое"), ("read", "Прочитано"), ("done", "Завершено")],
                        default="new",
                        max_length=16,
                        verbose_name="Статус",
                    ),
                ),
                (
                    "priority",
                    models.PositiveSmallIntegerField(
                        choices=[(1, "Низкий"), (2, "Обычный"), (3, "Высокий")],
                        default=2,
                        verbose_name="Приоритет",
                    ),
                ),
                ("requires_action", models.BooleanField(default=False, verbose_name="Требует действия")),
                (
                    "dedupe_key",
                    models.CharField(blank=True, max_length=180, null=True, unique=True, verbose_name="Ключ уникальности"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")),
                ("read_at", models.DateTimeField(blank=True, null=True, verbose_name="Дата прочтения")),
                ("done_at", models.DateTimeField(blank=True, null=True, verbose_name="Дата завершения")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Дата обновления")),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="sent_notifications",
                        to="employees.employees",
                        verbose_name="Инициатор",
                    ),
                ),
                (
                    "recipient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to="employees.employees",
                        verbose_name="Получатель",
                    ),
                ),
            ],
            options={
                "verbose_name": "Уведомление",
                "verbose_name_plural": "Уведомления",
                "db_table": "core_notification",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["recipient", "status", "-created_at"], name="core_notifi_recipie_77f260_idx"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["recipient", "requires_action", "status"], name="core_notifi_recipie_4acc57_idx"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["event_type", "created_at"], name="core_notifi_event_t_d934c3_idx"),
        ),
    ]
