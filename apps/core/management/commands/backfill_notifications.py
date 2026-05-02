from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_date

from apps.leave.services.notifications import DEFAULT_UPCOMING_REMINDER_DAYS_BEFORE, backfill_notifications_from_history


class Command(BaseCommand):
    help = "Create missing notifications from existing vacation requests, schedule transfers, reminders, and schedule changes"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days-before",
            type=int,
            default=DEFAULT_UPCOMING_REMINDER_DAYS_BEFORE,
            help="How many days before vacation start upcoming reminders are created.",
        )
        parser.add_argument(
            "--date",
            type=str,
            default="",
            help="Use this date as today in YYYY-MM-DD format.",
        )

    def handle(self, *args, **options):
        as_of_date = parse_date(options["date"]) if options["date"] else None
        if options["date"] and as_of_date is None:
            self.stderr.write(self.style.ERROR("Дата должна быть в формате YYYY-MM-DD."))
            return

        stats = backfill_notifications_from_history(
            days_before=options["days_before"],
            as_of_date=as_of_date,
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Уведомления синхронизированы: "
                f"создано={stats['notifications_created']}, "
                f"обновлено={stats['notifications_updated']}. "
                f"Заявки={stats['vacation_requests']}, "
                f"переносы={stats['schedule_changes']}, "
                f"напоминания={stats['upcoming_reminders']}, "
                f"изменения графика={stats['schedule_item_changes']}."
            )
        )
