from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


MANAGERS_GROUP_NAME = 'Managers'


def _looks_like_django_hash(value):
    if not value:
        return False
    return value.startswith(('pbkdf2_', 'argon2$', 'bcrypt$', 'scrypt$'))


def sync_employees_with_auth(apps, schema_editor):
    from django.contrib.auth.hashers import make_password

    Employees = apps.get_model('main', 'Employees')
    User = apps.get_model('auth', 'User')
    Group = apps.get_model('auth', 'Group')

    managers_group, _ = Group.objects.get_or_create(name=MANAGERS_GROUP_NAME)

    for employee in Employees.objects.all():
        username = f'employee_{employee.pk}'
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'first_name': employee.name[:150],
                'is_active': True,
            },
        )

        password_value = employee.password or ''
        if password_value:
            user.password = password_value if _looks_like_django_hash(password_value) else make_password(password_value)
        else:
            user.set_unusable_password()

        user.first_name = employee.name[:150]
        user.is_staff = employee.is_manager
        user.save()

        if employee.is_manager:
            user.groups.add(managers_group)
        else:
            user.groups.remove(managers_group)

        employee.user = user
        if password_value:
            employee.password = user.password
        employee.save(update_fields=['user', 'password'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0011_alter_preholidays_created_at_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='employees',
            name='user',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='employee_profile', to=settings.AUTH_USER_MODEL),
        ),
        migrations.RunPython(sync_employees_with_auth, noop_reverse),
    ]
