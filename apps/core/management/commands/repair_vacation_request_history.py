from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.services import can_approve_leave_for_employee
from apps.leave.models import VacationRequest
from apps.leave.services.approval_routes import get_expected_vacation_approver
from apps.leave.services.request_history import (
    get_vacation_submitted_at,
    rebuild_vacation_request_history,
)


class Command(BaseCommand):
    help = "Repair vacation request reviewers and chronological request history."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply changes. Without this flag the command only prints a dry-run summary.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        stats = {
            "checked": 0,
            "reviewers": 0,
            "dates": 0,
            "histories": 0,
            "pending_cleared": 0,
        }

        queryset = VacationRequest.objects.select_related("employee", "reviewed_by").order_by("id")

        context = transaction.atomic() if apply_changes else _noop_context()
        with context:
            for vacation in queryset:
                stats["checked"] += 1
                updates, history_created_at, history_submitted_at, history_reviewed_at = self._repair_payload(vacation)

                if "reviewed_by_id" in updates:
                    stats["reviewers"] += 1
                if "created_at" in updates or "reviewed_at" in updates:
                    stats["dates"] += 1
                if vacation.status == VacationRequest.STATUS_PENDING and (
                    "reviewed_by_id" in updates or "reviewed_at" in updates
                ):
                    stats["pending_cleared"] += 1

                if apply_changes and updates:
                    VacationRequest.objects.filter(pk=vacation.pk).update(**updates)
                    for field_name, value in updates.items():
                        setattr(vacation, field_name, value)

                if apply_changes:
                    rebuild_vacation_request_history(
                        vacation,
                        created_at=history_created_at,
                        submitted_at=history_submitted_at,
                        reviewed_at=history_reviewed_at,
                    )
                stats["histories"] += 1

        mode = "Применено" if apply_changes else "Dry-run"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode}: проверено={stats['checked']}, "
                f"согласующие={stats['reviewers']}, "
                f"даты={stats['dates']}, "
                f"истории={stats['histories']}, "
                f"очищено_ожидающих={stats['pending_cleared']}"
            )
        )
        if not apply_changes:
            self.stdout.write("Запустите команду с --apply, чтобы применить исправления.")

    def _repair_payload(self, vacation):
        updates = {}
        created_at = vacation.created_at or timezone.now()
        reviewed_at = vacation.reviewed_at

        if vacation.status == VacationRequest.STATUS_PENDING:
            if vacation.reviewed_by_id is not None:
                updates["reviewed_by_id"] = None
                vacation.reviewed_by = None
                vacation.reviewed_by_id = None
            if vacation.reviewed_at is not None:
                updates["reviewed_at"] = None
                vacation.reviewed_at = None
            return updates, created_at, get_vacation_submitted_at(created_at), None

        route = get_expected_vacation_approver(vacation.employee)
        expected_reviewer = route.employee
        current_reviewer = vacation.reviewed_by
        current_is_valid = (
            current_reviewer is not None
            and can_approve_leave_for_employee(current_reviewer, vacation.employee)
        )

        if expected_reviewer is not None and vacation.reviewed_by_id != expected_reviewer.id:
            updates["reviewed_by_id"] = expected_reviewer.id
            current_reviewer = expected_reviewer
            vacation.reviewed_by = expected_reviewer
            vacation.reviewed_by_id = expected_reviewer.id
        elif expected_reviewer is None and not current_is_valid and vacation.reviewed_by_id is not None:
            updates["reviewed_by_id"] = None
            current_reviewer = None
            vacation.reviewed_by = None
            vacation.reviewed_by_id = None

        if reviewed_at is None:
            reviewed_at = self._default_reviewed_at(vacation)
            updates["reviewed_at"] = reviewed_at
            vacation.reviewed_at = reviewed_at

        if reviewed_at <= created_at:
            created_at = reviewed_at - timedelta(days=2, minutes=vacation.id % 47)
            updates["created_at"] = created_at
            vacation.created_at = created_at

        submitted_at = get_vacation_submitted_at(created_at, reviewed_at)
        return updates, created_at, submitted_at, reviewed_at

    def _default_reviewed_at(self, vacation):
        review_date = min(vacation.start_date - timedelta(days=7), timezone.localdate())
        return timezone.make_aware(datetime(review_date.year, review_date.month, review_date.day, 15, 0))


class _noop_context:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, traceback):
        return False
