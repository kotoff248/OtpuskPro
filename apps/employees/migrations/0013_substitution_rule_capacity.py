from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("employees", "0012_populate_staffing_references"),
    ]

    operations = [
        migrations.AddField(
            model_name="productiongroupsubstitutionrule",
            name="max_covered_absences",
            field=models.PositiveSmallIntegerField(default=1, verbose_name="Закрывает отсутствующих"),
        ),
    ]
