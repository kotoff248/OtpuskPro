import random
from collections import Counter
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.services import sync_employee_user
from apps.employees.models import Departments, Employees
from apps.leave.models import VacationRequest
from apps.leave.services import (
    add_years_safe,
    get_chargeable_leave_days,
    get_employee_requestable_leave,
    sync_employee_vacation_metrics,
)


DEPARTMENT_SPECS = [
    {
        "name": "Производство",
        "head_position": "Начальник производства",
        "employee_positions": [
            "Горный мастер",
            "Ведущий инженер-технолог",
            "Машинист технологического оборудования",
            "Оператор производственной линии",
            "Инженер по качеству",
        ],
    },
    {
        "name": "Техническое обслуживание",
        "head_position": "Руководитель службы ТОиР",
        "employee_positions": [
            "Инженер по ремонту оборудования",
            "Механик участка",
            "Электромонтер",
            "Слесарь по ремонту оборудования",
            "Инженер-диагност",
        ],
    },
    {
        "name": "Промышленная безопасность",
        "head_position": "Начальник службы промышленной безопасности",
        "employee_positions": [
            "Инженер по охране труда",
            "Специалист по промышленной безопасности",
            "Инспектор по технике безопасности",
            "Инженер-эколог",
            "Ведущий специалист по рискам",
        ],
    },
    {
        "name": "Логистика",
        "head_position": "Руководитель логистики",
        "employee_positions": [
            "Специалист по логистике",
            "Диспетчер транспортного участка",
            "Координатор поставок",
            "Инженер по складской логистике",
            "Аналитик цепочки поставок",
        ],
    },
    {
        "name": "Финансы и закупки",
        "head_position": "Руководитель финансов и закупок",
        "employee_positions": [
            "Финансовый аналитик",
            "Экономист",
            "Специалист по закупкам",
            "Ведущий бухгалтер",
            "Контрактный менеджер",
        ],
    },
]

MALE_FIRST_NAMES = [
    "Алексей",
    "Дмитрий",
    "Иван",
    "Павел",
    "Егор",
    "Николай",
    "Сергей",
    "Максим",
    "Андрей",
    "Константин",
    "Олег",
    "Роман",
    "Виктор",
    "Артем",
    "Георгий",
]
FEMALE_FIRST_NAMES = [
    "Анна",
    "Мария",
    "Елена",
    "Ирина",
    "Ольга",
    "Наталья",
    "Светлана",
    "Татьяна",
    "Дарья",
    "Юлия",
    "Евгения",
    "Виктория",
]
MALE_LAST_NAMES = [
    "Иванов",
    "Петров",
    "Сидоров",
    "Федоров",
    "Кузнецов",
    "Смирнов",
    "Попов",
    "Соколов",
    "Лебедев",
    "Козлов",
    "Новиков",
    "Морозов",
    "Павлов",
    "Семенов",
    "Громов",
]
FEMALE_LAST_NAMES = [
    "Иванова",
    "Петрова",
    "Сидорова",
    "Федорова",
    "Кузнецова",
    "Смирнова",
    "Попова",
    "Соколова",
    "Лебедева",
    "Козлова",
    "Новикова",
    "Морозова",
    "Павлова",
    "Семенова",
    "Громова",
]
MALE_MIDDLE_NAMES = [
    "Александрович",
    "Дмитриевич",
    "Иванович",
    "Павлович",
    "Егорович",
    "Николаевич",
    "Сергеевич",
    "Максимович",
    "Андреевич",
    "Константинович",
    "Олегович",
    "Романович",
]
FEMALE_MIDDLE_NAMES = [
    "Александровна",
    "Дмитриевна",
    "Ивановна",
    "Павловна",
    "Егоровна",
    "Николаевна",
    "Сергеевна",
    "Максимовна",
    "Андреевна",
    "Константиновна",
    "Олеговна",
    "Романовна",
]

DEFAULT_PASSWORD = "1234"
EMPLOYEES_PER_DEPARTMENT = 20
HR_COUNT = 2
ENTERPRISE_HEAD_COUNT = 1
ACTIVE_STATUSES = {VacationRequest.STATUS_APPROVED, VacationRequest.STATUS_PENDING}
MAX_REALISTIC_AVAILABLE_DAYS = 104
PAID_OPERATIONAL_GAP_RANGE = (14, 30)


class NameFactory:
    def __init__(self):
        self._counters = {"male": 0, "female": 0}

    def next_name(self, gender):
        counter = self._counters[gender]
        self._counters[gender] += 1

        if gender == "female":
            first_names = FEMALE_FIRST_NAMES
            last_names = FEMALE_LAST_NAMES
            middle_names = FEMALE_MIDDLE_NAMES
        else:
            first_names = MALE_FIRST_NAMES
            last_names = MALE_LAST_NAMES
            middle_names = MALE_MIDDLE_NAMES

        return (
            last_names[(counter // len(first_names)) % len(last_names)],
            first_names[counter % len(first_names)],
            middle_names[((counter // (len(first_names) * len(last_names))) + counter) % len(middle_names)],
        )


class Command(BaseCommand):
    help = "Reset demo enterprise data and create realistic departments, employees, logins, and vacation history"

    def add_arguments(self, parser):
        parser.add_argument("--seed-value", type=int, default=42)

    @transaction.atomic
    def handle(self, *args, **options):
        self.rng = random.Random(options["seed_value"])
        self.today = timezone.localdate()
        self.name_factory = NameFactory()
        self.status_counts = Counter()

        self._reset_demo_data()
        departments = self._create_departments()
        enterprise_head = self._create_enterprise_head()
        authorized_person = self._create_authorized_person()
        hr_team = self._create_hr_team(departments[-1])
        department_heads = self._create_department_heads(departments)
        employees = self._create_department_employees(departments)

        everyone = [enterprise_head, *hr_team, *department_heads, *employees]
        for employee in everyone:
            self._seed_employee_vacations(employee)
            sync_employee_vacation_metrics(employee)

        self.stdout.write(
            self.style.SUCCESS(
                "Демо-база предприятия создана: "
                f"отделы={len(departments)}, "
                f"руководители_отделов={len(department_heads)}, "
                f"hr={len(hr_team)}, "
                f"директора={ENTERPRISE_HEAD_COUNT}, "
                f"сотрудники={len(employees)}"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Созданы заявки: "
                f"approved={self.status_counts[VacationRequest.STATUS_APPROVED]}, "
                f"pending={self.status_counts[VacationRequest.STATUS_PENDING]}, "
                f"rejected={self.status_counts[VacationRequest.STATUS_REJECTED]}"
            )
        )

    def _reset_demo_data(self):
        user_ids = list(Employees.objects.exclude(user_id=None).values_list("user_id", flat=True))

        VacationRequest.objects.all().delete()
        Employees.objects.all().delete()
        Departments.objects.all().delete()

        if user_ids:
            get_user_model().objects.filter(id__in=user_ids).delete()

    def _create_departments(self):
        return [Departments.objects.create(name=spec["name"]) for spec in DEPARTMENT_SPECS]

    def _create_enterprise_head(self):
        return self._create_employee(
            login="director_1",
            role=Employees.ROLE_ENTERPRISE_HEAD,
            position="Директор предприятия",
            department=None,
            gender="male",
            min_years=8,
            max_years=12,
        )

    def _create_authorized_person(self):
        employee = Employees.objects.create(
            login="admin_1",
            role=Employees.ROLE_AUTHORIZED_PERSON,
            position="Уполномоченное лицо",
            department=None,
            password=DEFAULT_PASSWORD,
        )
        sync_employee_user(employee, raw_password=DEFAULT_PASSWORD)
        return employee

    def _create_hr_team(self, department):
        positions = ["HR бизнес-партнер", "Ведущий HR-специалист"]
        genders = ["female", "female"]
        hr_team = []
        for index in range(HR_COUNT):
            hr_team.append(
                self._create_employee(
                    login=f"hr_{index + 1}",
                    role=Employees.ROLE_HR,
                    position=positions[index % len(positions)],
                    department=department,
                    gender=genders[index % len(genders)],
                    min_years=4,
                    max_years=9,
                )
            )
        return hr_team

    def _create_department_heads(self, departments):
        heads = []
        for index, (department, spec) in enumerate(zip(departments, DEPARTMENT_SPECS), start=1):
            heads.append(
                self._create_employee(
                    login=f"manager_{index}",
                    role=Employees.ROLE_DEPARTMENT_HEAD,
                    position=spec["head_position"],
                    department=department,
                    gender="male" if index % 2 else "female",
                    min_years=6,
                    max_years=11,
                )
            )
        return heads

    def _create_department_employees(self, departments):
        employees = []
        employee_index = 1
        for department, spec in zip(departments, DEPARTMENT_SPECS):
            for slot in range(EMPLOYEES_PER_DEPARTMENT):
                employees.append(
                    self._create_employee(
                        login=f"employ_{employee_index}",
                        role=Employees.ROLE_EMPLOYEE,
                        position=spec["employee_positions"][slot % len(spec["employee_positions"])],
                        department=department,
                        gender="female" if (employee_index + slot) % 4 == 0 else "male",
                        min_years=1,
                        max_years=10,
                    )
                )
                employee_index += 1
        return employees

    def _create_employee(self, login, role, position, department, gender, min_years, max_years):
        last_name, first_name, middle_name = self.name_factory.next_name(gender)
        start_days = self.rng.randint(min_years * 365, max_years * 365)
        date_joined = self.today - timedelta(days=start_days)

        employee = Employees.objects.create(
            login=login,
            last_name=last_name,
            first_name=first_name,
            middle_name=middle_name,
            position=position,
            role=role,
            date_joined=date_joined,
            annual_paid_leave_days=52,
            vacation_days=52,
            department=department,
            password=DEFAULT_PASSWORD,
        )
        sync_employee_user(employee, raw_password=DEFAULT_PASSWORD)
        return employee

    def _seed_employee_vacations(self, employee):
        occupied_periods = []
        paid_periods = []
        tenure_days = max((self.today - employee.date_joined).days, 0)
        requestable_days = int(get_employee_requestable_leave(employee, self.today))
        target_reserved_days = self._target_reserved_days(tenure_days, requestable_days)
        target_available_days = self._target_available_balance(tenure_days, requestable_days, target_reserved_days)
        target_used_paid_days = max(requestable_days - target_available_days - target_reserved_days, 0)
        working_years = self._build_working_year_windows(employee)
        year_budgets = self._allocate_paid_budget_by_working_year(working_years, target_used_paid_days)

        remaining_paid_budget = 0
        for year_window, year_budget in zip(working_years, year_budgets):
            remaining_paid_budget += self._seed_paid_history_for_working_year(
                employee,
                occupied_periods,
                paid_periods,
                year_window,
                year_budget,
            )
            self._maybe_create_historical_special_leave(
                employee,
                occupied_periods,
                paid_periods,
                year_window,
                tenure_days,
            )

        if remaining_paid_budget >= 5:
            remaining_paid_budget = self._backfill_paid_budget(
                employee,
                occupied_periods,
                paid_periods,
                working_years,
                remaining_paid_budget,
            )

        if tenure_days > 220 and target_reserved_days >= 5:
            self._create_future_pending_leave(employee, occupied_periods, paid_periods, target_reserved_days)
        elif tenure_days > 220 and self.rng.random() < 0.14:
            self._create_future_special_leave(employee, occupied_periods, paid_periods)

        if tenure_days > 120 and self.rng.random() < 0.32:
            self._create_rejected_leave(employee, occupied_periods, paid_periods)

    def _build_working_year_windows(self, employee):
        windows = []
        cursor = employee.date_joined
        while cursor <= self.today:
            window_end = add_years_safe(cursor, 1) - timedelta(days=1)
            windows.append(
                {
                    "start": cursor,
                    "end": window_end,
                    "completed": window_end < self.today,
                    "is_current": cursor <= self.today <= window_end,
                }
            )
            cursor = window_end + timedelta(days=1)
        return windows

    def _allocate_paid_budget_by_working_year(self, working_years, target_used_paid_days):
        budgets = [0] * len(working_years)
        completed_indexes = [index for index, window in enumerate(working_years) if window["completed"]]
        current_index = next((index for index, window in enumerate(working_years) if window["is_current"]), None)
        remaining_budget = max(target_used_paid_days, 0)

        for position, year_index in enumerate(completed_indexes):
            remaining_completed = len(completed_indexes) - position - 1
            minimum_for_remaining = remaining_completed * 14
            average_target = round(remaining_budget / max(len(completed_indexes) - position, 1))
            year_budget = max(14, min(52, average_target + self.rng.randint(-6, 6)))
            if remaining_budget - year_budget < minimum_for_remaining:
                year_budget = remaining_budget - minimum_for_remaining
            year_budget = max(14, min(52, year_budget))
            budgets[year_index] = year_budget
            remaining_budget -= year_budget

        if current_index is not None and remaining_budget > 0:
            current_cap = 52
            current_budget = min(max(0, remaining_budget), current_cap)
            budgets[current_index] = current_budget
            remaining_budget -= current_budget

        backfill_indexes = list(reversed(completed_indexes))
        while remaining_budget > 0 and backfill_indexes:
            made_progress = False
            for year_index in backfill_indexes:
                if remaining_budget <= 0:
                    break
                extra_capacity = 52 - budgets[year_index]
                if extra_capacity <= 0:
                    continue
                extra_budget = min(extra_capacity, remaining_budget, self.rng.choice([5, 7, 10, 14]))
                budgets[year_index] += extra_budget
                remaining_budget -= extra_budget
                made_progress = True
            if not made_progress:
                break

        return budgets

    def _seed_paid_history_for_working_year(self, employee, occupied_periods, paid_periods, year_window, year_budget):
        if year_budget < 5:
            return year_budget

        budget_left = year_budget
        period_start = year_window["start"]
        period_end = min(year_window["end"], self.today - timedelta(days=7))
        if period_start > period_end:
            return year_budget

        if year_window["completed"] and budget_left >= 14:
            main_duration = self._pick_paid_main_duration(budget_left)
            budget_left -= self._create_paid_leave_block(
                employee,
                occupied_periods,
                paid_periods,
                period_start,
                period_end,
                duration=main_duration,
                min_gap_days=self.rng.randint(*PAID_OPERATIONAL_GAP_RANGE) if paid_periods else 0,
            )

        extras_allowed = 3 if year_window["completed"] else 2
        extras_created = 0
        while budget_left >= 5 and extras_created < extras_allowed:
            consumed = 0
            for extra_duration in [duration for duration in [14, 10, 7, 5] if duration <= budget_left]:
                consumed = self._create_paid_leave_block(
                    employee,
                    occupied_periods,
                    paid_periods,
                    period_start,
                    period_end,
                    duration=extra_duration,
                    min_gap_days=self.rng.randint(*PAID_OPERATIONAL_GAP_RANGE),
                )
                if consumed > 0:
                    break

            if consumed <= 0:
                break
            budget_left -= consumed
            extras_created += 1

        return max(budget_left, 0)

    def _pick_paid_main_duration(self, available_budget):
        if available_budget >= 42:
            variants = [28, 21, 14]
        elif available_budget >= 28:
            variants = [21, 14]
        else:
            variants = [14]
        return self.rng.choice([duration for duration in variants if duration <= available_budget] or [14])

    def _pick_paid_extra_duration(self, available_budget):
        variants = [14, 10, 7, 5]
        eligible = [duration for duration in variants if duration <= available_budget]
        if not eligible:
            return None
        return self.rng.choice(eligible)

    def _create_paid_leave_block(
        self,
        employee,
        occupied_periods,
        paid_periods,
        window_start,
        window_end,
        duration,
        min_gap_days=0,
    ):
        slot = self._find_free_slot(
            occupied_periods,
            window_start,
            window_end,
            duration,
            gap_periods=paid_periods,
            min_gap_days=min_gap_days,
        )
        if slot is None:
            return 0

        start_date, end_date = slot
        self._create_request(employee, start_date, end_date, "paid", VacationRequest.STATUS_APPROVED)
        occupied_periods.append((start_date, end_date))
        paid_periods.append((start_date, end_date))
        return get_chargeable_leave_days(start_date, end_date, "paid")

    def _backfill_paid_budget(self, employee, occupied_periods, paid_periods, working_years, remaining_budget):
        for year_window in reversed(working_years):
            if remaining_budget < 5:
                break
            if not year_window["completed"]:
                continue
            extra_duration = self._pick_paid_extra_duration(remaining_budget)
            if extra_duration is None:
                break
            consumed = self._create_paid_leave_block(
                employee,
                occupied_periods,
                paid_periods,
                year_window["start"],
                min(year_window["end"], self.today - timedelta(days=7)),
                duration=extra_duration,
                min_gap_days=self.rng.randint(*PAID_OPERATIONAL_GAP_RANGE),
            )
            if consumed <= 0:
                continue
            remaining_budget -= consumed
        return max(remaining_budget, 0)

    def _maybe_create_historical_special_leave(self, employee, occupied_periods, paid_periods, year_window, tenure_days):
        if not year_window["completed"]:
            return

        vacation_type = None
        if self.rng.random() < 0.16:
            vacation_type = "unpaid"
        elif tenure_days > 365 and self.rng.random() < 0.09:
            vacation_type = "study"

        if vacation_type is None:
            return

        self._create_special_leave(
            employee,
            occupied_periods,
            paid_periods,
            year_window["start"],
            min(year_window["end"], self.today - timedelta(days=14)),
            vacation_type,
            VacationRequest.STATUS_APPROVED,
        )

    def _create_special_leave(self, employee, occupied_periods, paid_periods, window_start, window_end, vacation_type, status):
        duration = self._pick_duration(window_start, window_end, [3, 5, 7, 10])
        if duration is None:
            return False

        slot = self._find_free_slot(
            occupied_periods,
            window_start,
            window_end,
            duration,
            gap_periods=paid_periods if vacation_type == "paid" else None,
            min_gap_days=self.rng.randint(*PAID_OPERATIONAL_GAP_RANGE) if vacation_type == "paid" else 0,
        )
        if slot is None:
            return False

        start_date, end_date = slot
        self._create_request(employee, start_date, end_date, vacation_type, status)
        occupied_periods.append((start_date, end_date))
        if vacation_type == "paid":
            paid_periods.append((start_date, end_date))
        return True

    def _consume_remaining_paid_budget(self, employee, occupied_periods, earliest_paid_start, remaining_paid_budget):
        if remaining_paid_budget < 5:
            return remaining_paid_budget

        year_windows = []
        for year_cursor in range(max(earliest_paid_start.year, self.today.year - 9), self.today.year + 1):
            window_start = max(date(year_cursor, 1, 1), earliest_paid_start)
            window_end = min(date(year_cursor, 12, 31), self.today - timedelta(days=21))
            if window_start <= window_end:
                year_windows.append((window_start, window_end))

        for pass_index in range(3):
            if remaining_paid_budget < 5:
                break

            made_progress = False
            for window_start, window_end in year_windows:
                duration = self._pick_duration(
                    window_start,
                    window_end,
                    [35, 28, 21, 14, 10, 7] if pass_index == 0 else [21, 14, 10, 7],
                )
                if duration is None:
                    continue

                duration = min(duration, remaining_paid_budget)
                if duration < 5:
                    continue

                slot = self._find_free_slot(occupied_periods, window_start, window_end, duration)
                if slot is None:
                    continue

                start_date, end_date = slot
                self._create_request(employee, start_date, end_date, "paid", VacationRequest.STATUS_APPROVED)
                occupied_periods.append((start_date, end_date))
                remaining_paid_budget -= get_chargeable_leave_days(start_date, end_date, "paid")
                made_progress = True

                if remaining_paid_budget < 5:
                    break

            if not made_progress:
                break

        return max(remaining_paid_budget, 0)

    def _target_available_balance(self, tenure_days, requestable_days, target_reserved_days):
        tenure_years = tenure_days / 365
        available_limit = max(requestable_days - target_reserved_days, 0)

        if tenure_years >= 8:
            if self.rng.random() < 0.12:
                target = self.rng.randint(55, 85)
            else:
                target = self.rng.randint(16, 42)
        elif tenure_years >= 5:
            if self.rng.random() < 0.10:
                target = self.rng.randint(45, 70)
            else:
                target = self.rng.randint(14, 36)
        elif tenure_years >= 2:
            target = self.rng.randint(8, 28)
        else:
            target = self.rng.randint(3, 18)

        return min(target, available_limit, MAX_REALISTIC_AVAILABLE_DAYS)

    def _target_reserved_days(self, tenure_days, requestable_days):
        if tenure_days <= 220 or requestable_days < 5:
            return 0

        if self.rng.random() > 0.42:
            return 0

        variants = [7, 10, 14]
        if requestable_days >= 21 and self.rng.random() < 0.25:
            variants.append(21)
        return min(self.rng.choice(variants), requestable_days)

    def _approved_probability(self, tenure_days, year_cursor):
        tenure_years = tenure_days / 365
        if year_cursor == self.today.year:
            return 0.38 if tenure_years < 3 else 0.62
        if tenure_years >= 7:
            return 0.95
        if tenure_years >= 4:
            return 0.84
        return 0.68

    def _create_approved_leave(self, employee, occupied_periods, window_start, window_end, remaining_paid_budget):
        vacation_type = self.rng.choices(
            population=["paid", "paid", "paid", "unpaid", "study"],
            weights=[55, 20, 10, 10, 5],
            k=1,
        )[0]
        durations = [7, 10, 14, 21, 28] if vacation_type == "paid" else [3, 5, 7, 10]
        duration = self._pick_duration(window_start, window_end, durations)
        if duration is None:
            return remaining_paid_budget

        if vacation_type == "paid":
            duration = min(duration, remaining_paid_budget if remaining_paid_budget > 0 else duration)
            if duration < 5:
                return remaining_paid_budget

        slot = self._find_free_slot(occupied_periods, window_start, window_end, duration)
        if slot is None:
            return remaining_paid_budget

        start_date, end_date = slot
        self._create_request(employee, start_date, end_date, vacation_type, VacationRequest.STATUS_APPROVED)
        occupied_periods.append((start_date, end_date))

        if vacation_type == "paid":
            remaining_paid_budget -= get_chargeable_leave_days(start_date, end_date, vacation_type)
        return max(remaining_paid_budget, 0)

    def _create_secondary_past_leave(self, employee, occupied_periods, window_start, window_end, remaining_paid_budget):
        vacation_type = self.rng.choices(
            population=["paid", "unpaid", "study"],
            weights=[45, 35, 20],
            k=1,
        )[0]
        duration = self._pick_duration(window_start, window_end, [3, 5, 7])
        if duration is None:
            return remaining_paid_budget

        if vacation_type == "paid":
            duration = min(duration, remaining_paid_budget)
            if duration < 3:
                return remaining_paid_budget

        slot = self._find_free_slot(occupied_periods, window_start, window_end, duration)
        if slot is None:
            return remaining_paid_budget

        start_date, end_date = slot
        self._create_request(employee, start_date, end_date, vacation_type, VacationRequest.STATUS_APPROVED)
        occupied_periods.append((start_date, end_date))
        if vacation_type == "paid":
            remaining_paid_budget -= get_chargeable_leave_days(start_date, end_date, vacation_type)
        return max(remaining_paid_budget, 0)

    def _create_current_approved_leave(self, employee, occupied_periods, remaining_paid_budget):
        duration = min(self.rng.choice([7, 10, 14]), remaining_paid_budget)
        if duration < 5:
            return remaining_paid_budget

        start_date = self.today - timedelta(days=self.rng.randint(0, min(duration - 1, 5)))
        end_date = start_date + timedelta(days=duration - 1)
        if self._period_overlaps(occupied_periods, start_date, end_date):
            return remaining_paid_budget

        self._create_request(employee, start_date, end_date, "paid", VacationRequest.STATUS_APPROVED)
        occupied_periods.append((start_date, end_date))
        remaining_paid_budget -= get_chargeable_leave_days(start_date, end_date, "paid")
        return max(remaining_paid_budget, 0)

    def _create_future_pending_leave(self, employee, occupied_periods, paid_periods, remaining_paid_budget):
        duration = self._pick_duration(
            self.today + timedelta(days=20),
            self.today + timedelta(days=210),
            [21, 14, 10, 7],
        )
        if duration is None:
            return

        duration = min(duration, remaining_paid_budget)
        if duration < 5:
            return

        slot = self._find_free_slot(
            occupied_periods,
            self.today + timedelta(days=20),
            self.today + timedelta(days=210),
            duration,
            gap_periods=paid_periods,
            min_gap_days=self.rng.randint(*PAID_OPERATIONAL_GAP_RANGE),
        )
        if slot is None:
            return

        start_date, end_date = slot
        self._create_request(employee, start_date, end_date, "paid", VacationRequest.STATUS_PENDING)
        occupied_periods.append((start_date, end_date))
        paid_periods.append((start_date, end_date))

    def _create_future_special_leave(self, employee, occupied_periods, paid_periods):
        vacation_type = self.rng.choice(["unpaid", "study"])
        self._create_special_leave(
            employee,
            occupied_periods,
            paid_periods,
            self.today + timedelta(days=20),
            self.today + timedelta(days=210),
            vacation_type,
            VacationRequest.STATUS_PENDING,
        )

    def _create_rejected_leave(self, employee, occupied_periods, paid_periods):
        window_start = self.today - timedelta(days=120)
        window_end = self.today + timedelta(days=160)
        vacation_type = self.rng.choice(["paid", "unpaid", "study"])
        duration_options = [7, 10, 14] if vacation_type == "paid" else [3, 5, 7, 10]
        duration = self._pick_duration(window_start, window_end, duration_options)
        if duration is None:
            return

        slot = self._find_free_slot(
            occupied_periods,
            window_start,
            window_end,
            duration,
            gap_periods=paid_periods if vacation_type == "paid" else None,
            min_gap_days=self.rng.randint(*PAID_OPERATIONAL_GAP_RANGE) if vacation_type == "paid" else 0,
        )
        if slot is None:
            return

        start_date, end_date = slot
        self._create_request(employee, start_date, end_date, vacation_type, VacationRequest.STATUS_REJECTED)
        occupied_periods.append((start_date, end_date))
        if vacation_type == "paid":
            paid_periods.append((start_date, end_date))

    def _create_request(self, employee, start_date, end_date, vacation_type, status):
        VacationRequest.objects.create(
            employee=employee,
            start_date=start_date,
            end_date=end_date,
            vacation_type=vacation_type,
            status=status,
        )
        self.status_counts[status] += 1

    def _pick_duration(self, window_start, window_end, variants):
        if window_start > window_end:
            return None

        max_duration = (window_end - window_start).days + 1
        eligible = [variant for variant in variants if variant <= max_duration]
        if not eligible:
            return None
        return self.rng.choice(eligible)

    def _find_free_slot(
        self,
        occupied_periods,
        window_start,
        window_end,
        duration,
        gap_periods=None,
        min_gap_days=0,
        max_attempts=80,
    ):
        if window_start > window_end:
            return None

        latest_start = window_end - timedelta(days=duration - 1)
        if latest_start < window_start:
            return None

        for _ in range(max_attempts):
            offset = self.rng.randint(0, (latest_start - window_start).days)
            start_date = window_start + timedelta(days=offset)
            end_date = start_date + timedelta(days=duration - 1)
            if not self._period_overlaps(occupied_periods, start_date, end_date) and not self._period_overlaps_with_gap(
                gap_periods or [],
                start_date,
                end_date,
                min_gap_days,
            ):
                return start_date, end_date

        cursor = window_start
        while cursor <= latest_start:
            end_date = cursor + timedelta(days=duration - 1)
            if not self._period_overlaps(occupied_periods, cursor, end_date) and not self._period_overlaps_with_gap(
                gap_periods or [],
                cursor,
                end_date,
                min_gap_days,
            ):
                return cursor, end_date
            cursor += timedelta(days=1)
        return None

    def _period_overlaps(self, occupied_periods, start_date, end_date):
        return any(not (end_date < current_start or start_date > current_end) for current_start, current_end in occupied_periods)

    def _period_overlaps_with_gap(self, occupied_periods, start_date, end_date, min_gap_days):
        if min_gap_days <= 0:
            return False

        padded_start = start_date - timedelta(days=min_gap_days)
        padded_end = end_date + timedelta(days=min_gap_days)
        return any(not (padded_end < current_start or padded_start > current_end) for current_start, current_end in occupied_periods)
