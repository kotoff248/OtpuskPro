from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone

from apps.accounts.services import sync_employee_user
from apps.core.models import Notification
from apps.employees.models import Employees
from apps.leave.models import VacationPreference, VacationPreferenceCollection
from apps.leave.services.dates import add_months_safe
from apps.leave.services.preferences import build_preference_collection_summary
from apps.leave.tests.base import LeaveTestCase


class VacationPreferenceCollectionTests(LeaveTestCase):
    def _year(self):
        return timezone.localdate().year + 1

    def _deadline(self):
        return timezone.localdate() + timedelta(days=14)

    def _start_collection(self, *, demo_autofill=False):
        self.client.force_login(self.hr_employee.user)
        payload = {
            "year": self._year(),
            "deadline": self._deadline().isoformat(),
        }
        if demo_autofill:
            payload["demo_autofill"] = "on"
        return self.client.post(reverse("preferences_collection_start"), payload)

    def test_only_hr_can_start_and_finish_collection(self):
        year = self._year()
        self.client.force_login(self.employee.user)
        response = self.client.post(
            reverse("preferences_collection_start"),
            {"year": year, "deadline": self._deadline().isoformat()},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(VacationPreferenceCollection.objects.filter(year=year).exists())

        self._start_collection()
        collection = VacationPreferenceCollection.objects.get(year=year)
        self.assertEqual(collection.status, VacationPreferenceCollection.STATUS_OPEN)
        self.assertEqual(collection.started_by_id, self.hr_employee.id)

        self.client.force_login(self.department_head.user)
        response = self.client.post(reverse("preferences_collection_finish", args=[year]))
        collection.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(collection.status, VacationPreferenceCollection.STATUS_OPEN)

        self.client.force_login(self.hr_employee.user)
        response = self.client.post(reverse("preferences_collection_finish", args=[year]))
        collection.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(collection.status, VacationPreferenceCollection.STATUS_FINISHED)
        self.assertEqual(collection.finished_by_id, self.hr_employee.id)

    def test_calendar_collection_actions_target_next_planning_year(self):
        current_year = timezone.localdate().year
        planning_year = self._year()
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(f"{reverse('calendar')}?view=year&year={current_year}")
        self.assertEqual(response.context["calendar_preference_collection"]["year"], planning_year)
        self.assertContains(response, f'name="year" value="{planning_year}"')

        response = self.client.post(
            reverse("preferences_collection_start"),
            {"year": current_year, "deadline": self._deadline().isoformat()},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(VacationPreferenceCollection.objects.filter(year=current_year).exists())

    def test_start_creates_pending_preferences_and_notifications(self):
        year = self._year()
        self._start_collection()

        self.assertTrue(
            VacationPreference.objects.filter(
                year=year,
                employee=self.employee,
                priority=VacationPreference.PRIORITY_PRIMARY,
                status=VacationPreference.STATUS_PENDING,
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.employee,
                event_type=Notification.TYPE_PREFERENCES_COLLECTION_STARTED,
                requires_action=True,
                status=Notification.STATUS_NEW,
                action_url=reverse("vacation_preferences", args=[year]),
            ).exists()
        )

    def test_demo_autofill_fills_majority_but_leaves_pending_tasks(self):
        year = self._year()
        demo_first_employee = Employees.objects.create(
            last_name="Первый",
            first_name="Сотрудник",
            middle_name="Демо",
            login="employ_1",
            position="Специалист",
            employee_position=self.engineering_position,
            department=self.engineering,
            date_joined=self.today - timedelta(days=420),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        self._start_collection(demo_autofill=True)

        eligible_count = Employees.objects.exclude(role__in=Employees.SERVICE_ROLES).count()
        filled_count = (
            VacationPreference.objects.filter(year=year, status=VacationPreference.STATUS_FILLED)
            .values("employee_id")
            .distinct()
            .count()
        )
        pending_count = (
            VacationPreference.objects.filter(year=year, status=VacationPreference.STATUS_PENDING)
            .values("employee_id")
            .distinct()
            .count()
        )
        skipped_count = (
            VacationPreference.objects.filter(year=year, status=VacationPreference.STATUS_SKIPPED)
            .values("employee_id")
            .distinct()
            .count()
        )

        self.assertGreaterEqual(filled_count, eligible_count // 2)
        self.assertGreater(pending_count, 0)
        self.assertEqual(
            list(
                VacationPreference.objects.filter(employee=demo_first_employee, year=year)
                .order_by("priority")
                .values_list("status", flat=True)
            ),
            [VacationPreference.STATUS_PENDING, VacationPreference.STATUS_PENDING],
        )
        self.assertEqual(
            Notification.objects.filter(
                event_type=Notification.TYPE_PREFERENCES_COLLECTION_STARTED,
                status=Notification.STATUS_NEW,
            ).count(),
            pending_count,
        )
        self.assertEqual(
            Notification.objects.filter(
                event_type=Notification.TYPE_PREFERENCES_COLLECTION_STARTED,
            )
            .values("recipient_id")
            .distinct()
            .count(),
            eligible_count,
        )
        self.assertEqual(
            Notification.objects.filter(
                event_type=Notification.TYPE_PREFERENCES_COLLECTION_STARTED,
                status=Notification.STATUS_DONE,
            ).count(),
            filled_count + skipped_count,
        )

    def test_restarting_collection_refreshes_previous_preferences(self):
        year = self._year()
        self._start_collection()
        collection = VacationPreferenceCollection.objects.get(year=year)

        self.client.force_login(self.employee.user)
        self.client.post(
            reverse("vacation_preferences", args=[year]),
            {
                "primary_start_date": date(year, 7, 1).isoformat(),
                "primary_end_date": date(year, 7, 14).isoformat(),
                "backup_start_date": date(year, 9, 1).isoformat(),
                "backup_end_date": date(year, 9, 14).isoformat(),
                "comment": "Семейная поездка.",
            },
        )

        self.client.force_login(self.hr_employee.user)
        self.client.post(
            reverse("preferences_collection_start"),
            {
                "year": collection.year,
                "deadline": self._deadline().isoformat(),
                "demo_autofill": "on",
            },
        )

        primary = VacationPreference.objects.get(
            employee=self.employee,
            year=year,
            priority=VacationPreference.PRIORITY_PRIMARY,
        )
        self.assertNotEqual(primary.comment, "Семейная поездка.")
        self.assertIn(
            primary.status,
            {
                VacationPreference.STATUS_FILLED,
                VacationPreference.STATUS_PENDING,
                VacationPreference.STATUS_SKIPPED,
            },
        )
        self.assertEqual(
            VacationPreference.objects.filter(year=year).count(),
            Employees.objects.exclude(role__in=Employees.SERVICE_ROLES).count() * 2,
        )
        pending_count = (
            VacationPreference.objects.filter(year=year, status=VacationPreference.STATUS_PENDING)
            .values("employee_id")
            .distinct()
            .count()
        )
        self.assertEqual(
            Notification.objects.filter(
                event_type=Notification.TYPE_PREFERENCES_COLLECTION_STARTED,
                status=Notification.STATUS_NEW,
            ).count(),
            pending_count,
        )

    def test_start_without_demo_resets_old_seed_preferences_to_pending(self):
        year = self._year()
        VacationPreference.objects.create(
            employee=self.employee,
            year=year,
            priority=VacationPreference.PRIORITY_PRIMARY,
            start_date=date(year, 6, 1),
            end_date=date(year, 6, 14),
            status=VacationPreference.STATUS_FILLED,
            created_automatically=True,
        )
        VacationPreference.objects.create(
            employee=self.employee,
            year=year,
            priority=VacationPreference.PRIORITY_BACKUP,
            start_date=date(year, 8, 1),
            end_date=date(year, 8, 14),
            status=VacationPreference.STATUS_FILLED,
            created_automatically=True,
        )

        self._start_collection(demo_autofill=False)

        self.assertEqual(
            VacationPreference.objects.filter(
                employee=self.employee,
                year=year,
                status=VacationPreference.STATUS_PENDING,
            ).count(),
            2,
        )
        summary = build_preference_collection_summary(year)
        self.assertEqual(summary["ready"], 0)
        self.assertEqual(summary["pending"], summary["total"])

    def test_preference_page_hides_paid_leave_hint_after_waiting_period(self):
        year = self._year()
        self._start_collection()
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("vacation_preferences", args=[year]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Право на оплачиваемый отпуск")
        self.assertContains(response, 'data-preferences-form')
        self.assertContains(response, f'data-collection-year="{year}"')
        self.assertContains(response, 'data-preference-state="pending"')
        self.assertContains(response, 'data-calendar-return-link')
        self.assertContains(response, f"Сбор {year}-го открыт")
        self.assertContains(response, "Итого выбрано")
        self.assertContains(response, "vacation-preferences.js")
        self.assertEqual(response.context["sidebar_section"], "calendar")
        self.assertTrue(response.context["page_header_back_link"]["use_calendar_memory"])

    def test_preference_page_shows_paid_leave_hint_for_newcomer(self):
        year = self._year()
        self._start_collection()
        newcomer = Employees.objects.create(
            last_name="Новичков",
            first_name="Павел",
            middle_name="Игоревич",
            login="newcomer-preference-user",
            position="Специалист",
            employee_position=self.engineering_position,
            department=self.engineering,
            date_joined=timezone.localdate(),
            annual_paid_leave_days=52,
            role=Employees.ROLE_EMPLOYEE,
        )
        sync_employee_user(newcomer, raw_password="newcomer-pass")
        self.client.force_login(newcomer.user)

        response = self.client.get(reverse("vacation_preferences", args=[year]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Право на оплачиваемый отпуск")
        self.assertContains(response, add_months_safe(timezone.localdate(), 6).strftime("%d.%m.%Y"))

    def test_employee_can_submit_or_skip_preferences_and_complete_notification(self):
        year = self._year()
        self._start_collection()
        self.client.force_login(self.employee.user)

        response = self.client.post(
            reverse("vacation_preferences", args=[year]),
            {
                "primary_start_date": date(year, 6, 1).isoformat(),
                "primary_end_date": date(year, 6, 14).isoformat(),
                "backup_start_date": date(year, 8, 1).isoformat(),
                "backup_end_date": date(year, 8, 14).isoformat(),
                "comment": "Хочу летом.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            VacationPreference.objects.filter(
                employee=self.employee,
                year=year,
                status=VacationPreference.STATUS_FILLED,
            ).count(),
            2,
        )
        notification = Notification.objects.get(
            dedupe_key=f"{Notification.TYPE_PREFERENCES_COLLECTION_STARTED}:{year}:{self.employee.id}"
        )
        self.assertEqual(notification.status, Notification.STATUS_DONE)

        response = self.client.post(
            reverse("vacation_preferences", args=[year]),
            {
                "no_preferences": "on",
                "comment": "Даты не принципиальны.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            VacationPreference.objects.filter(
                employee=self.employee,
                year=year,
                status=VacationPreference.STATUS_SKIPPED,
            ).count(),
            2,
        )
        summary = build_preference_collection_summary(year)
        self.assertGreaterEqual(summary["ready"], 1)
        self.assertEqual(summary["ready"], summary["total"] - summary["attention"])

    def test_closed_collection_blocks_employee_edits_and_closes_notifications(self):
        year = self._year()
        self._start_collection()

        self.client.force_login(self.hr_employee.user)
        self.client.post(reverse("preferences_collection_finish", args=[year]))

        self.client.force_login(self.employee.user)
        response = self.client.post(
            reverse("vacation_preferences", args=[year]),
            {
                "primary_start_date": date(year, 6, 1).isoformat(),
                "primary_end_date": date(year, 6, 14).isoformat(),
                "backup_start_date": date(year, 8, 1).isoformat(),
                "backup_end_date": date(year, 8, 14).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            VacationPreference.objects.filter(
                employee=self.employee,
                year=year,
                status=VacationPreference.STATUS_FILLED,
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                event_type=Notification.TYPE_PREFERENCES_COLLECTION_STARTED,
                status=Notification.STATUS_NEW,
            ).exists()
        )

    def test_non_planning_year_collection_is_read_only_even_if_open(self):
        current_year = timezone.localdate().year
        planning_year = self._year()
        VacationPreferenceCollection.objects.create(
            year=current_year,
            status=VacationPreferenceCollection.STATUS_OPEN,
            deadline=self._deadline(),
            started_by=self.hr_employee,
        )
        self.client.force_login(self.employee.user)

        get_response = self.client.get(reverse("vacation_preferences", args=[current_year]))
        self.assertContains(get_response, f"Сейчас пожелания собираются на {planning_year} год")
        self.assertContains(get_response, f'data-planning-year="{planning_year}"')

        response = self.client.post(
            reverse("vacation_preferences", args=[current_year]),
            {
                "primary_start_date": date(current_year, 6, 1).isoformat(),
                "primary_end_date": date(current_year, 6, 14).isoformat(),
                "backup_start_date": date(current_year, 8, 1).isoformat(),
                "backup_end_date": date(current_year, 8, 14).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            VacationPreference.objects.filter(
                employee=self.employee,
                year=current_year,
                status=VacationPreference.STATUS_FILLED,
            ).exists()
        )

    def test_new_employee_is_attached_to_open_collection(self):
        year = self._year()
        self._start_collection()
        self.client.force_login(self.hr_employee.user)

        response = self.client.post(
            reverse("employees"),
            {
                "last_name": "Новый",
                "first_name": "Сотрудник",
                "middle_name": "Тестович",
                "login": "new-preference-user",
                "password": "1234",
                "employee_position": self.engineering_position.id,
                "department": self.engineering.id,
                "role": Employees.ROLE_EMPLOYEE,
                "date_joined": timezone.localdate().isoformat(),
            },
        )

        self.assertEqual(response.status_code, 302)
        employee = Employees.objects.get(login="new-preference-user")
        self.assertTrue(
            VacationPreference.objects.filter(
                employee=employee,
                year=year,
                status=VacationPreference.STATUS_PENDING,
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=employee,
                event_type=Notification.TYPE_PREFERENCES_COLLECTION_STARTED,
                status=Notification.STATUS_NEW,
            ).exists()
        )
