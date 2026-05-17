from django.core.management.base import BaseCommand, CommandError

from apps.core.models import DemoDataResetJob
from apps.core.services.demo_reset_jobs import update_demo_data_reset_job_progress
from apps.core.services.demo_seed import DemoVacationSeedRunner
from apps.core.services.demo_seed.constants import DEFAULT_SCHEDULE_HISTORY_YEARS


class Command(BaseCommand):
    help = "Reset demo enterprise data and create realistic departments, employees, logins, and vacation history"

    def execute(self, *args, **options):
        try:
            return super().execute(*args, **options)
        except Exception as exc:
            progress_job_id = options.get("progress_job_id") or getattr(self, "progress_job_id", None)
            if progress_job_id:
                runner = getattr(self, "_seed_runner", None)
                update_demo_data_reset_job_progress(
                    progress_job_id,
                    status=DemoDataResetJob.STATUS_FAILED,
                    progress_percent=getattr(runner, "_last_progress_percent", 0),
                    stage_label="Ошибка пересоздания",
                    error_message=str(exc),
                    finished=True,
                )
            raise

    def add_arguments(self, parser):
        parser.add_argument("--seed-value", type=int, default=42)
        parser.add_argument(
            "--history-years",
            type=int,
            default=DEFAULT_SCHEDULE_HISTORY_YEARS,
            help="How many full years before the current year to include in vacation history.",
        )
        parser.add_argument(
            "--fast",
            action="store_true",
            help="Create a smaller but structurally complete dataset for tests and quick checks.",
        )
        parser.add_argument(
            "--confirm-reset",
            action="store_true",
            help="Confirm deleting existing demo data before rebuilding the demo enterprise dataset.",
        )
        parser.add_argument(
            "--progress-job-id",
            type=int,
            default=None,
            help="DemoDataResetJob id for background progress updates.",
        )

    def handle(self, *args, **options):
        if not options["confirm_reset"]:
            raise CommandError(
                "seed_vacation_requests deletes existing demo employees, departments, vacation requests, "
                "schedules, and linked users. Run again with --confirm-reset to rebuild demo data."
            )

        self.progress_job_id = options.get("progress_job_id")
        self._seed_runner = DemoVacationSeedRunner(stdout=self.stdout, style=self.style)
        return self._seed_runner.run(
            seed_value=options["seed_value"],
            history_years=options["history_years"],
            fast=options["fast"],
            progress_job_id=options.get("progress_job_id"),
        )
