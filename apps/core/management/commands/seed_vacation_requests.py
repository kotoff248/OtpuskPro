import random
from datetime import date, timedelta

from django.core.management.base import BaseCommand

from apps.employees.models import Employees
from apps.leave.models import VacationRequest


class Command(BaseCommand):
    help = "Reset vacation requests and generate organic demo data"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true")
        parser.add_argument("--seed", action="store_true")
        parser.add_argument("--seed-value", type=int, default=42)

    def handle(self, *args, **options):
        do_reset = options["reset"]
        do_seed = options["seed"]
        seed_value = options["seed_value"]

        if not do_reset and not do_seed:
            self.stdout.write(self.style.WARNING("Ничего не выполнено. Используйте --reset и/или --seed."))
            return

        random.seed(seed_value)
        today = date.today()

        if do_reset:
            deleted_count, _ = VacationRequest.objects.all().delete()
            for employee in Employees.objects.all():
                employee.used_up_days = 0
                employee.is_working = True
                employee.save(update_fields=["used_up_days", "is_working"])
            self.stdout.write(self.style.SUCCESS(f"Удалено заявок: {deleted_count}"))

        if not do_seed:
            return

        employees = list(Employees.objects.select_related("department").order_by("id"))
        created_counts = {"approved": 0, "pending": 0, "rejected": 0}

        for index, employee in enumerate(employees):
            employee_requests = []
            requests_target = (index % 4) + 1
            if index % 5 == 0:
                requests_target = 0

            cursor = today - timedelta(days=120) + timedelta(days=index * 3)
            for request_index in range(requests_target):
                duration = random.choice([5, 7, 10, 14])
                gap = random.choice([12, 18, 24, 35])
                start_date = cursor + timedelta(days=gap)
                end_date = start_date + timedelta(days=duration - 1)
                cursor = end_date

                if request_index == 0 and index % 3 == 0:
                    status = VacationRequest.STATUS_APPROVED
                elif request_index == requests_target - 1 and index % 2 == 0:
                    status = VacationRequest.STATUS_PENDING
                elif request_index % 3 == 0:
                    status = VacationRequest.STATUS_REJECTED
                else:
                    status = random.choice(
                        [
                            VacationRequest.STATUS_APPROVED,
                            VacationRequest.STATUS_PENDING,
                            VacationRequest.STATUS_REJECTED,
                        ]
                    )

                request_obj = VacationRequest.objects.create(
                    employee=employee,
                    start_date=start_date,
                    end_date=end_date,
                    vacation_type=random.choice(["paid", "paid", "unpaid", "study"]),
                    status=status,
                )
                employee_requests.append(request_obj)
                created_counts[status] += 1

            approved_days = sum(
                (request_obj.end_date - request_obj.start_date).days + 1
                for request_obj in employee_requests
                if request_obj.status == VacationRequest.STATUS_APPROVED
            )
            employee.used_up_days = approved_days
            employee.is_working = not any(
                request_obj.status == VacationRequest.STATUS_APPROVED and request_obj.start_date <= today <= request_obj.end_date
                for request_obj in employee_requests
            )
            employee.save(update_fields=["used_up_days", "is_working"])

        self.stdout.write(
            self.style.SUCCESS(
                "Созданы заявки: "
                f"одобрено={created_counts['approved']}, "
                f"в ожидании={created_counts['pending']}, "
                f"отклонено={created_counts['rejected']}"
            )
        )
