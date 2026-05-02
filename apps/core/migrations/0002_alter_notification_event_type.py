from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
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
                    ("schedule_item_changed_by_manager", "График отпуска изменён руководителем"),
                    ("upcoming_vacation_reminder", "Скоро отпуск"),
                ],
                max_length=64,
                verbose_name="Тип события",
            ),
        ),
    ]
