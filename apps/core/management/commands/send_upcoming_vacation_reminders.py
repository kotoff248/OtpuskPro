from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_date

from apps.leave.services.notifications import DEFAULT_UPCOMING_REMINDER_DAYS_BEFORE, send_upcoming_vacation_reminders


class Command(BaseCommand):
    help = "Create upcoming vacation reminder notifications for vacations that start soon"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days-before",
            type=int,
            default=DEFAULT_UPCOMING_REMINDER_DAYS_BEFORE,
            help="How many days before vacation start reminders are created.",
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

        stats = send_upcoming_vacation_reminders(
            days_before=options["days_before"],
            as_of_date=as_of_date,
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Напоминания об отпусках синхронизированы: "
                f"создано={stats['notifications_created']}, "
                f"обновлено={stats['notifications_updated']}, "
                f"напоминания={stats['upcoming_reminders']}."
            )
        )
