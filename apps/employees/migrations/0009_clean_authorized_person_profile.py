from django.db import migrations


def clean_authorized_person_profiles(apps, schema_editor):
    Employees = apps.get_model("employees", "Employees")
    User = apps.get_model("auth", "User")

    for employee in Employees.objects.filter(role="authorized_person"):
        employee.last_name = ""
        employee.first_name = ""
        employee.middle_name = ""
        employee.position = ""
        employee.department_id = None
        employee.annual_paid_leave_days = 0
        employee.vacation_days = 0
        employee.used_up_days = 0
        employee.is_working = False
        employee.save(
            update_fields=[
                "last_name",
                "first_name",
                "middle_name",
                "position",
                "department",
                "annual_paid_leave_days",
                "vacation_days",
                "used_up_days",
                "is_working",
            ]
        )

        if employee.user_id:
            User.objects.filter(pk=employee.user_id).update(first_name="", last_name="")


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0008_employees_is_active_employee"),
    ]

    operations = [
        migrations.RunPython(clean_authorized_person_profiles, migrations.RunPython.noop),
    ]
