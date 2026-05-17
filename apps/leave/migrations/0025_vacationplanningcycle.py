from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("employees", "0013_substitution_rule_capacity"),
        ("leave", "0024_backfill_vacationrequest_decision_ai"),
    ]

    operations = [
        migrations.CreateModel(
            name="VacationPlanningCycle",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("year", models.PositiveIntegerField(unique=True, verbose_name="Год планирования")),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Активный"), ("closed", "Закрыт")],
                        default="active",
                        max_length=16,
                        verbose_name="Статус",
                    ),
                ),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="Дата запуска")),
                ("closed_at", models.DateTimeField(blank=True, null=True, verbose_name="Дата закрытия")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Дата обновления")),
                (
                    "started_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="started_vacation_planning_cycles",
                        to="employees.employees",
                        verbose_name="Запустил",
                    ),
                ),
            ],
            options={
                "verbose_name": "Цикл планирования отпусков",
                "verbose_name_plural": "Циклы планирования отпусков",
                "db_table": "leave_vacationplanningcycle",
                "ordering": ["-year"],
            },
        ),
        migrations.AddConstraint(
            model_name="vacationplanningcycle",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "active")),
                fields=("status",),
                name="unique_active_vacation_planning_cycle",
            ),
        ),
    ]
