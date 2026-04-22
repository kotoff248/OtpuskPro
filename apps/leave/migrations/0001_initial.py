import django.db.models.deletion
from django.db import migrations, models


VACATION_SQL = """
DO $$
DECLARE
    idx record;
    con record;
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'main_vacationrequest'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'leave_vacationrequest'
    ) THEN
        ALTER TABLE main_vacationrequest RENAME TO leave_vacationrequest;
    ELSIF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'leave_vacationrequest'
    ) THEN
        CREATE TABLE leave_vacationrequest (
            id bigserial PRIMARY KEY,
            start_date date NOT NULL,
            end_date date NOT NULL,
            vacation_type varchar(50) NOT NULL DEFAULT 'paid',
            status varchar(20) NOT NULL DEFAULT 'pending',
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            employee_id bigint NOT NULL REFERENCES employees_employees(id) DEFERRABLE INITIALLY DEFERRED
        );
        CREATE INDEX leave_vacationrequest_employee_id_idx ON leave_vacationrequest(employee_id);
    END IF;

    IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'main_vacationrequest_id_seq')
       AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'leave_vacationrequest_id_seq') THEN
        ALTER SEQUENCE main_vacationrequest_id_seq RENAME TO leave_vacationrequest_id_seq;
    END IF;

    FOR idx IN
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = 'public'
          AND tablename = 'leave_vacationrequest'
          AND indexname LIKE 'main_vacationrequest%'
    LOOP
        EXECUTE format(
            'ALTER INDEX %I RENAME TO %I',
            idx.indexname,
            replace(idx.indexname, 'main_vacationrequest', 'leave_vacationrequest')
        );
    END LOOP;

    FOR con IN
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'leave_vacationrequest'::regclass
          AND conname LIKE 'main_vacationrequest%'
    LOOP
        EXECUTE format(
            'ALTER TABLE leave_vacationrequest RENAME CONSTRAINT %I TO %I',
            con.conname,
            replace(con.conname, 'main_vacationrequest', 'leave_vacationrequest')
        );
    END LOOP;
END $$;
"""


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("employees", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(VACATION_SQL, reverse_sql=migrations.RunSQL.noop),
            ],
            state_operations=[
                migrations.CreateModel(
                    name="VacationRequest",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("start_date", models.DateField(verbose_name="Дата начала")),
                        ("end_date", models.DateField(verbose_name="Дата окончания")),
                        (
                            "vacation_type",
                            models.CharField(
                                choices=[("paid", "Оплачиваемый"), ("unpaid", "Неоплачиваемый"), ("study", "Учебный")],
                                default="paid",
                                max_length=50,
                                verbose_name="Тип отпуска",
                            ),
                        ),
                        (
                            "status",
                            models.CharField(
                                choices=[("pending", "В ожидании"), ("approved", "Одобрено"), ("rejected", "Отклонено")],
                                default="pending",
                                max_length=20,
                                verbose_name="Статус",
                            ),
                        ),
                        ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")),
                        (
                            "employee",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="vacation_requests",
                                to="employees.employees",
                                verbose_name="Сотрудник",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "Заявка на отпуск",
                        "verbose_name_plural": "Заявки на отпуск",
                        "db_table": "leave_vacationrequest",
                        "ordering": ["-created_at"],
                    },
                ),
            ],
        ),
    ]
