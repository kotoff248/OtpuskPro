from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0007_alter_employees_role_add_authorized_person"),
    ]

    operations = [
        migrations.AddField(
            model_name="employees",
            name="is_active_employee",
            field=models.BooleanField(default=True, verbose_name="Активный сотрудник"),
        ),
    ]
