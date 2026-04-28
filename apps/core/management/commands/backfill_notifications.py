from django.core.management.base import BaseCommand

from apps.leave.services.notifications import backfill_pending_approval_notifications


class Command(BaseCommand):
    help = "Create missing approval notifications for existing pending vacation requests and schedule transfers"

    def handle(self, *args, **options):
        stats = backfill_pending_approval_notifications()
        self.stdout.write(
            self.style.SUCCESS(
                "Недостающие уведомления созданы: "
                f"{stats['notifications_created']}. "
                f"Заявок: {stats['vacation_requests']}, "
                f"переносов: {stats['schedule_changes']}."
            )
        )
