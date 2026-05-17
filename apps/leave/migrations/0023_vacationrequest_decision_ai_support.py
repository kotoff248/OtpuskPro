from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leave", "0022_vacationrequest_ai_support"),
    ]

    operations = [
        migrations.AddField(
            model_name="vacationrequest",
            name="decision_ai_confidence",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=5,
                null=True,
                verbose_name="Уверенность ИИ на момент решения",
            ),
        ),
        migrations.AddField(
            model_name="vacationrequest",
            name="decision_ai_evaluated_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Дата оценки ИИ при решении"),
        ),
        migrations.AddField(
            model_name="vacationrequest",
            name="decision_ai_explanation",
            field=models.TextField(blank=True, default="", verbose_name="Пояснение ИИ на момент решения"),
        ),
        migrations.AddField(
            model_name="vacationrequest",
            name="decision_ai_model_version",
            field=models.CharField(
                blank=True,
                default="",
                max_length=80,
                verbose_name="Версия ИИ-модели на момент решения",
            ),
        ),
        migrations.AddField(
            model_name="vacationrequest",
            name="decision_ai_recommendation",
            field=models.CharField(
                blank=True,
                default="",
                max_length=32,
                verbose_name="Рекомендация ИИ на момент решения",
            ),
        ),
        migrations.AddField(
            model_name="vacationrequest",
            name="decision_ai_score",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=6,
                null=True,
                verbose_name="Оценка ИИ на момент решения",
            ),
        ),
        migrations.AddField(
            model_name="vacationrequest",
            name="decision_ai_scorer_kind",
            field=models.CharField(
                blank=True,
                default="",
                max_length=32,
                verbose_name="Тип ИИ-оценки на момент решения",
            ),
        ),
        migrations.AddConstraint(
            model_name="vacationrequest",
            constraint=models.CheckConstraint(
                check=models.Q(("decision_ai_score__isnull", True))
                | (models.Q(("decision_ai_score__gte", 0)) & models.Q(("decision_ai_score__lte", 100))),
                name="vacation_request_decision_ai_score_0_100",
            ),
        ),
        migrations.AddConstraint(
            model_name="vacationrequest",
            constraint=models.CheckConstraint(
                check=models.Q(("decision_ai_confidence__isnull", True))
                | (
                    models.Q(("decision_ai_confidence__gte", 0))
                    & models.Q(("decision_ai_confidence__lte", 100))
                ),
                name="vacation_request_decision_ai_confidence_0_100",
            ),
        ),
    ]
