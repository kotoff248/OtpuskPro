from django.db import migrations, models


def split_full_name(value):
    parts = [part for part in (value or "").split() if part]
    if not parts:
        return "", "", ""
    if len(parts) == 1:
        return parts[0], "", ""
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return parts[0], parts[1], " ".join(parts[2:])


def forwards_fill_name_parts(apps, schema_editor):
    Employees = apps.get_model("employees", "Employees")
    for employee in Employees.objects.all():
        employee.last_name, employee.first_name, employee.middle_name = split_full_name(employee.name)
        employee.save(update_fields=["last_name", "first_name", "middle_name"])


def backwards_fill_name(apps, schema_editor):
    Employees = apps.get_model("employees", "Employees")
    for employee in Employees.objects.all():
        employee.name = " ".join(
            part for part in [employee.last_name, employee.first_name, employee.middle_name] if part
        ).strip()
        employee.save(update_fields=["name"])


class Migration(migrations.Migration):

    dependencies = [
        ("employees", "0002_alter_departments_options_alter_employees_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="employees",
            name="first_name",
            field=models.CharField(default="", max_length=100, verbose_name="Имя"),
        ),
        migrations.AddField(
            model_name="employees",
            name="last_name",
            field=models.CharField(default="", max_length=100, verbose_name="Фамилия"),
        ),
        migrations.AddField(
            model_name="employees",
            name="middle_name",
            field=models.CharField(default="", max_length=100, verbose_name="Отчество"),
        ),
        migrations.RunPython(forwards_fill_name_parts, backwards_fill_name),
        migrations.RemoveField(
            model_name="employees",
            name="name",
        ),
    ]
