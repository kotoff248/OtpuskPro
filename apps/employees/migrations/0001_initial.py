import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


DEPARTMENTS_SQL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'main_departments'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'employees_departments'
    ) THEN
        ALTER TABLE main_departments RENAME TO employees_departments;
    ELSIF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'employees_departments'
    ) THEN
        CREATE TABLE employees_departments (
            id bigserial PRIMARY KEY,
            name varchar(150) NOT NULL UNIQUE,
            date_added timestamptz NOT NULL
        );
    END IF;

    IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'main_departments_id_seq')
       AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'employees_departments_id_seq') THEN
        ALTER SEQUENCE main_departments_id_seq RENAME TO employees_departments_id_seq;
    END IF;
END $$;
"""


EMPLOYEES_SQL = """
DO $$
DECLARE
    idx record;
    con record;
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'main_employees'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'employees_employees'
    ) THEN
        ALTER TABLE main_employees RENAME TO employees_employees;
    ELSIF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'employees_employees'
    ) THEN
        CREATE TABLE employees_employees (
            id bigserial PRIMARY KEY,
            name varchar(100) NOT NULL,
            login varchar(150) NOT NULL UNIQUE,
            position varchar(100) NOT NULL,
            date_joined date NOT NULL,
            vacation_days integer NOT NULL,
            used_up_days integer NOT NULL,
            is_working boolean NOT NULL,
            password varchar(128) NOT NULL DEFAULT '',
            is_manager boolean NOT NULL,
            department_id bigint NULL REFERENCES employees_departments(id) DEFERRABLE INITIALLY DEFERRED,
            user_id integer NULL UNIQUE REFERENCES auth_user(id) DEFERRABLE INITIALLY DEFERRED
        );
        CREATE INDEX employees_employees_department_id_idx ON employees_employees(department_id);
    END IF;

    IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'main_employees_id_seq')
       AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'employees_employees_id_seq') THEN
        ALTER SEQUENCE main_employees_id_seq RENAME TO employees_employees_id_seq;
    END IF;

    FOR idx IN
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = 'public'
          AND tablename = 'employees_employees'
          AND indexname LIKE 'main_employees%'
    LOOP
        EXECUTE format(
            'ALTER INDEX %I RENAME TO %I',
            idx.indexname,
            replace(idx.indexname, 'main_employees', 'employees_employees')
        );
    END LOOP;

    FOR con IN
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'employees_employees'::regclass
          AND conname LIKE 'main_employees%'
    LOOP
        EXECUTE format(
            'ALTER TABLE employees_employees RENAME CONSTRAINT %I TO %I',
            con.conname,
            replace(con.conname, 'main_employees', 'employees_employees')
        );
    END LOOP;
END $$;
"""


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(DEPARTMENTS_SQL, reverse_sql=migrations.RunSQL.noop),
                migrations.RunSQL(EMPLOYEES_SQL, reverse_sql=migrations.RunSQL.noop),
            ],
            state_operations=[
                migrations.CreateModel(
                    name="Departments",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("name", models.CharField(max_length=150, unique=True, verbose_name="Название отдела")),
                        ("date_added", models.DateTimeField(default=django.utils.timezone.now, verbose_name="Дата добавления")),
                    ],
                    options={
                        "verbose_name": "Отдел",
                        "verbose_name_plural": "Отделы",
                        "db_table": "employees_departments",
                    },
                ),
                migrations.CreateModel(
                    name="Employees",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("name", models.CharField(max_length=100, verbose_name="ФИО")),
                        ("login", models.CharField(max_length=150, unique=True, verbose_name="Логин")),
                        ("position", models.CharField(max_length=100, verbose_name="Должность")),
                        ("date_joined", models.DateField(default=django.utils.timezone.now, verbose_name="Дата начала работы")),
                        (
                            "vacation_days",
                            models.PositiveIntegerField(
                                default=0,
                                validators=[django.core.validators.MaxValueValidator(52)],
                                verbose_name="Количество отпускных дней",
                            ),
                        ),
                        (
                            "used_up_days",
                            models.PositiveIntegerField(
                                default=0,
                                validators=[django.core.validators.MaxValueValidator(52)],
                                verbose_name="Использованные дни",
                            ),
                        ),
                        ("is_working", models.BooleanField(default=True, verbose_name="Работает")),
                        (
                            "password",
                            models.CharField(
                                blank=True,
                                default="",
                                max_length=128,
                                verbose_name="Служебный пароль (legacy)",
                            ),
                        ),
                        ("is_manager", models.BooleanField(default=False, verbose_name="Руководитель")),
                        (
                            "department",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                to="employees.departments",
                                verbose_name="Отдел",
                            ),
                        ),
                        (
                            "user",
                            models.OneToOneField(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="employee_profile",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "Сотрудник",
                        "verbose_name_plural": "Сотрудники",
                        "db_table": "employees_employees",
                    },
                ),
            ],
        ),
    ]
