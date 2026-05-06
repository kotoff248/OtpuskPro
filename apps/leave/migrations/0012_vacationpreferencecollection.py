from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("employees", "0013_substitution_rule_capacity"),
        ("leave", "0011_vacation_request_history"),
    ]

    operations = [
        migrations.CreateModel(
            name="VacationPreferenceCollection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("year", models.PositiveIntegerField(unique=True, verbose_name="Год")),
                (
                    "status",
                    models.CharField(
                        choices=[("open", "Открыт"), ("finished", "Завершён")],
                        default="open",
                        max_length=20,
                        verbose_name="Статус",
                    ),
                ),
                ("deadline", models.DateField(verbose_name="Срок заполнения")),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="Дата запуска")),
                ("finished_at", models.DateTimeField(blank=True, null=True, verbose_name="Дата завершения")),
                ("demo_autofill_enabled", models.BooleanField(default=False, verbose_name="Демо-автозаполнение")),
                (
                    "finished_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="finished_vacation_preference_collections",
                        to="employees.employees",
                        verbose_name="Завершил",
                    ),
                ),
                (
                    "started_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="started_vacation_preference_collections",
                        to="employees.employees",
                        verbose_name="Запустил",
                    ),
                ),
            ],
            options={
                "verbose_name": "Сбор пожеланий по отпуску",
                "verbose_name_plural": "Сборы пожеланий по отпуску",
                "db_table": "leave_vacationpreference_collection",
                "ordering": ["-year"],
            },
        ),
        migrations.AddIndex(
            model_name="vacationpreferencecollection",
            index=models.Index(fields=["status", "year"], name="leave_vacat_status_626071_idx"),
        ),
    ]
