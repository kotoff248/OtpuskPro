from django.db import migrations


def backfill_decision_ai_snapshots(apps, schema_editor):
    vacation_request = apps.get_model("leave", "VacationRequest")
    queryset = (
        vacation_request.objects.exclude(status="pending")
        .filter(
            decision_ai_score__isnull=True,
            ai_score__isnull=False,
        )
        .exclude(ai_explanation="")
    )

    for request in queryset.iterator():
        request.decision_ai_score = request.ai_score
        request.decision_ai_confidence = request.ai_confidence
        request.decision_ai_model_version = request.ai_model_version
        request.decision_ai_recommendation = request.ai_recommendation
        request.decision_ai_explanation = request.ai_explanation
        request.decision_ai_scorer_kind = request.ai_scorer_kind
        request.decision_ai_evaluated_at = request.reviewed_at or request.created_at
        request.save(
            update_fields=[
                "decision_ai_score",
                "decision_ai_confidence",
                "decision_ai_model_version",
                "decision_ai_recommendation",
                "decision_ai_explanation",
                "decision_ai_scorer_kind",
                "decision_ai_evaluated_at",
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("leave", "0023_vacationrequest_decision_ai_support"),
    ]

    operations = [
        migrations.RunPython(backfill_decision_ai_snapshots, migrations.RunPython.noop),
    ]
