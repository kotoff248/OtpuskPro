from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_demodataresetjob"),
    ]

    operations = [
        migrations.AlterField(
            model_name="notification",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("vacation_request_created", "Создана заявка на отпуск"),
                    ("vacation_request_approved", "Заявка на отпуск одобрена"),
                    ("vacation_request_rejected", "Заявка на отпуск отклонена"),
                    ("schedule_change_created", "Создан запрос переноса"),
                    ("schedule_change_approved", "Перенос одобрен"),
                    ("schedule_change_rejected", "Перенос отклонён"),
                    ("preferences_collection_started", "Начат сбор пожеланий"),
                    ("schedule_review_requested", "Запрошено согласование графика"),
                    ("schedule_approved", "График отпусков утверждён"),
                    ("schedule_item_changed_by_manager", "График отпуска изменён руководителем"),
                    ("upcoming_vacation_reminder", "Скоро отпуск"),
                    ("urgent_closure_department_review", "Закрытие остатка у руководителя"),
                    ("urgent_closure_employee_review", "Закрытие остатка у сотрудника"),
                    ("urgent_closure_hr_finalization", "Закрытие остатка у HR"),
                    ("urgent_closure_status", "Статус закрытия остатка"),
                ],
                max_length=64,
                verbose_name="Тип события",
            ),
        ),
    ]
