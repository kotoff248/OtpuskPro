import json
from datetime import date, timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.accounts.services import sync_employee_user
from apps.core.models import Notification
from apps.employees.models import Employees
from apps.leave.models import (
    DepartmentWorkload,
    VacationPreference,
    VacationPreferenceCollection,
    VacationSchedule,
    VacationScheduleCandidate,
    VacationScheduleCandidateFeedback,
    VacationScheduleCandidatePackage,
    VacationScheduleCandidatePackagePeriod,
    VacationScheduleGenerationRun,
    VacationScheduleDepartmentApproval,
    VacationScheduleItem,
    VacationScheduleManualSuggestionCache,
    VacationUrgentClosureRequest,
)
from apps.leave.services.dates import add_months_safe, get_chargeable_leave_days
from apps.leave.services.preferences import (
    build_preference_collection_summary,
    get_employee_preference_pair_map,
    get_employee_preference_state_map,
    preference_readiness_url,
)
from apps.leave.services.schedule_drafts import (
    _build_employee_schedule_planning_need_from_rows,
    _build_auto_generation_candidates,
    _build_draft_generation_context,
    _build_preference_generation_candidates,
    auto_place_remaining_schedule_draft,
    build_manual_schedule_draft_preview,
    build_schedule_draft_auto_place_preview,
    place_manual_schedule_draft_items,
)
from apps.leave.services.schedule_planning import schedule_planning_url
from apps.leave.services.candidate_scoring import ACTIVE_CANDIDATE_SCORER_VERSION
from apps.leave.tests.base import LeaveTestCase


class VacationPreferenceCollectionTests(LeaveTestCase):
    def test_bulk_preference_state_map_matches_single_employee_states(self):
        year = self._year()
        VacationPreference.objects.filter(year=year).delete()
        VacationPreference.objects.bulk_create(
            [
                VacationPreference(
                    employee=self.employee,
                    year=year,
                    priority=VacationPreference.PRIORITY_PRIMARY,
                    start_date=date(year, 6, 1),
                    end_date=date(year, 6, 14),
                    status=VacationPreference.STATUS_FILLED,
                ),
                VacationPreference(
                    employee=self.employee,
                    year=year,
                    priority=VacationPreference.PRIORITY_BACKUP,
                    start_date=date(year, 8, 1),
                    end_date=date(year, 8, 14),
                    status=VacationPreference.STATUS_FILLED,
                ),
                VacationPreference(
                    employee=self.department_head,
                    year=year,
                    priority=VacationPreference.PRIORITY_PRIMARY,
                    status=VacationPreference.STATUS_SKIPPED,
                ),
                VacationPreference(
                    employee=self.hr_employee,
                    year=year,
                    priority=VacationPreference.PRIORITY_PRIMARY,
                    status=VacationPreference.STATUS_PENDING,
                ),
            ]
        )

        with self.assertNumQueries(1):
            state_by_employee = get_employee_preference_state_map(
                [
                    self.employee.id,
                    self.department_head.id,
                    self.hr_employee.id,
                    self.outsider.id,
                ],
                year,
            )

        self.assertEqual(state_by_employee[self.employee.id], VacationPreference.STATUS_FILLED)
        self.assertEqual(state_by_employee[self.department_head.id], VacationPreference.STATUS_SKIPPED)
        self.assertEqual(state_by_employee[self.hr_employee.id], VacationPreference.STATUS_PENDING)
        self.assertEqual(state_by_employee[self.outsider.id], "missing")

    def test_bulk_preference_pair_map_uses_first_preference_by_priority(self):
        year = self._year()
        VacationPreference.objects.filter(year=year).delete()
        first_primary = VacationPreference.objects.create(
            employee=self.employee,
            year=year,
            priority=VacationPreference.PRIORITY_PRIMARY,
            start_date=date(year, 6, 1),
            end_date=date(year, 6, 14),
            status=VacationPreference.STATUS_FILLED,
        )
        VacationPreference.objects.create(
            employee=self.employee,
            year=year,
            priority=VacationPreference.PRIORITY_PRIMARY,
            start_date=date(year, 7, 1),
            end_date=date(year, 7, 14),
            status=VacationPreference.STATUS_FILLED,
        )
        backup = VacationPreference.objects.create(
            employee=self.employee,
            year=year,
            priority=VacationPreference.PRIORITY_BACKUP,
            start_date=date(year, 9, 1),
            end_date=date(year, 9, 14),
            status=VacationPreference.STATUS_FILLED,
        )

        with self.assertNumQueries(1):
            pair_by_employee = get_employee_preference_pair_map([self.employee.id, self.outsider.id], year)

        self.assertEqual(pair_by_employee[self.employee.id][VacationPreference.PRIORITY_PRIMARY], first_primary)
        self.assertEqual(pair_by_employee[self.employee.id][VacationPreference.PRIORITY_BACKUP], backup)
        self.assertIsNone(pair_by_employee[self.outsider.id][VacationPreference.PRIORITY_PRIMARY])

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

    def test_enterprise_head_sees_collection_readiness_without_management_actions(self):
        year = self._year()
        self._start_collection()

        self.client.force_login(self.enterprise_head.user)
        response = self.client.get(f"{reverse('calendar')}?view=year&year={year}")

        self.assertEqual(response.status_code, 200)
        collection_context = response.context["calendar_preference_collection"]
        self.assertTrue(collection_context["can_view"])
        self.assertFalse(collection_context["can_manage"])
        self.assertEqual(collection_context["readiness_status_key"], "open")
        self.assertContains(response, "Сбор пожеланий")
        self.assertContains(response, "Сбор идет")
        self.assertContains(response, "Не ответили")
        self.assertContains(response, "Без пожеланий")
        self.assertNotContains(response, "Начать сбор пожеланий")
        self.assertNotContains(response, "Завершить сбор")

        finish_response = self.client.post(reverse("preferences_collection_finish", args=[year]))
        collection = VacationPreferenceCollection.objects.get(year=year)
        self.assertEqual(finish_response.status_code, 302)
        self.assertEqual(collection.status, VacationPreferenceCollection.STATUS_OPEN)

        self.client.force_login(self.hr_employee.user)
        response = self.client.get(f"{reverse('calendar')}?view=year&year={year}")
        self.assertContains(response, "Завершить сбор")
        self.client.post(reverse("preferences_collection_finish", args=[year]))

        self.client.force_login(self.enterprise_head.user)
        response = self.client.get(f"{reverse('calendar')}?view=year&year={year}")

        collection_context = response.context["calendar_preference_collection"]
        self.assertEqual(collection_context["readiness_status_key"], "ready")
        self.assertTrue(collection_context["draft_ready"])
        self.assertContains(response, "Готово к черновику")
        self.assertNotContains(response, "Завершить сбор")

    def test_calendar_preference_status_links_to_readiness_page(self):
        year = self._year()
        self._start_collection()
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(f"{reverse('calendar')}?view=year&year={year}")

        self.assertContains(response, f'href="{preference_readiness_url(year)}"')
        self.assertContains(response, "data-app-link")

    def test_hr_can_view_and_finish_readiness_page(self):
        year = self._year()
        self._start_collection()
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("preference_collection_readiness", args=[year]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Готовность сбора")
        self.assertContains(response, "Ответили")
        self.assertContains(response, "Не ответили")
        self.assertContains(response, "Без пожеланий")
        self.assertContains(response, "Завершить сбор")
        self.assertContains(response, "preference-readiness-segmented")
        self.assertContains(response, "data-preference-readiness-search")
        self.assertContains(response, "js/preference-readiness.js")
        self.assertEqual(response.context["summary"]["not_answered"], response.context["summary"]["total"])

        response = self.client.post(
            reverse("preferences_collection_finish", args=[year]),
            {"next": reverse("preference_collection_readiness", args=[year])},
        )

        self.assertRedirects(response, reverse("preference_collection_readiness", args=[year]))
        collection = VacationPreferenceCollection.objects.get(year=year)
        self.assertEqual(collection.status, VacationPreferenceCollection.STATUS_FINISHED)

    def test_readiness_page_marks_new_hires(self):
        year = self._year()
        self.employee.date_joined = timezone.localdate()
        self.employee.save(update_fields=["date_joined"])
        self._start_collection()
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("preference_collection_readiness", args=[year]))

        self.assertEqual(response.status_code, 200)
        rows_by_employee = {row["employee"].id: row for row in response.context["rows"]}
        self.assertEqual(rows_by_employee[self.employee.id]["new_hire_badge"]["label"], "Новичок")
        self.assertContains(response, 'class="new-hire-badge"')
        self.assertContains(response, "person_add")
        self.assertContains(response, "Работает меньше 6 месяцев")

    def test_hr_can_start_collection_from_planning_stage(self):
        year = self._year()
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(f"{reverse('schedule_planning', args=[year])}?stage=collection")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["can_start_collection"])
        self.assertContains(response, "Открыть сбор")
        self.assertContains(response, "Начать сбор пожеланий")
        self.assertContains(response, "calendar-action-btn calendar-action-btn--preferences")
        self.assertContains(response, "fact_check")
        self.assertEqual(
            response.context["calendar_preference_collection"]["start_next_url"],
            schedule_planning_url(year, "collection"),
        )

    def test_hr_can_start_collection_from_readiness_page(self):
        year = self._year()
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(
            reverse("preference_collection_readiness", args=[year]),
            {
                "from": "schedule_planning",
                "back_url": f"{reverse('schedule_planning', args=[year])}?stage=collection",
                "back_label": "К планированию",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["can_start_collection"])
        self.assertContains(response, "Не начат")
        self.assertContains(response, "Начать сбор пожеланий")
        self.assertContains(response, "calendar-action-btn calendar-action-btn--preferences")
        self.assertContains(response, "fact_check")
        self.assertEqual(response.context["calendar_preference_collection"]["start_next_url"], response.context["current_path"])

    def test_start_collection_respects_next_url(self):
        year = self._year()
        next_url = schedule_planning_url(year, "collection")
        self.client.force_login(self.hr_employee.user)

        response = self.client.post(
            reverse("preferences_collection_start"),
            {
                "year": year,
                "deadline": self._deadline().isoformat(),
                "next": next_url,
            },
        )

        self.assertRedirects(response, next_url)
        self.assertTrue(VacationPreferenceCollection.objects.filter(year=year).exists())

    def test_hr_can_open_schedule_planning_hub(self):
        year = self._year()
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("schedule_planning", args=[year]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sidebar_section"], "schedule_planning")
        self.assertEqual(response.context["selected_stage"], "calendar")
        self.assertContains(response, "Планирование графика")
        self.assertContains(response, "schedule-planning-roadmap")
        self.assertNotContains(response, "schedule-planning-stage-nav")
        self.assertContains(response, "css/pages/schedule-planning.css")
        self.assertContains(response, 'data-sidebar-key="schedule-planning"')
        self.assertContains(response, 'aria-current="page"')
        self.assertContains(response, "from=schedule_planning")
        for label in ["График", "Сбор", "Черновик", "Проверка", "Финал"]:
            self.assertContains(response, label)

    def test_full_calendar_opened_from_planning_keeps_planning_sidebar_active(self):
        year = self._year()
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(
            reverse("calendar"),
            {
                "view": "year",
                "year": year,
                "from": "schedule_planning",
                "back_url": reverse("schedule_planning", args=[year]),
                "back_label": "К планированию",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sidebar_section"], "schedule_planning")
        planning_link = self._sidebar_link_html(response, "schedule-planning")
        calendar_link = self._sidebar_link_html(response, "calendar")
        self.assertIn('aria-current="page"', planning_link)
        self.assertIn('data-sidebar-default-href=', planning_link)
        self.assertNotIn('aria-current="page"', calendar_link)

    def test_readiness_from_planning_preserves_planning_context_links(self):
        year = self._year()
        self._start_collection()
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(
            reverse("preference_collection_readiness", args=[year]),
            {
                "from": "schedule_planning",
                "back_url": f"{reverse('schedule_planning', args=[year])}?stage=collection",
                "back_label": "К планированию",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sidebar_section"], "schedule_planning")
        self.assertContains(response, "from=schedule_planning")
        self.assertContains(response, "back_url=")

    def test_schedule_planning_current_redirects_to_planning_year(self):
        year = self._year()
        self.client.force_login(self.hr_employee.user)

        response = self.client.get(reverse("schedule_planning_current"))

        self.assertRedirects(response, reverse("schedule_planning", args=[year]))

    def test_regular_employee_cannot_access_schedule_planning_or_sidebar(self):
        year = self._year()
        self.client.force_login(self.employee.user)

        response = self.client.get(reverse("schedule_planning", args=[year]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("calendar"))

        calendar_response = self.client.get(reverse("calendar"))
        self.assertNotContains(calendar_response, 'data-sidebar-key="schedule-planning"')

    def test_department_head_opens_schedule_planning_for_pending_review(self):
        year = self._year()
        schedule = VacationSchedule.objects.create(
            year=year,
            status=VacationSchedule.STATUS_DEPARTMENT_REVIEW,
            created_by=self.hr_employee,
        )
        VacationScheduleDepartmentApproval.objects.create(
            schedule=schedule,
            department=self.engineering,
            department_head=self.department_head,
            status=VacationScheduleDepartmentApproval.STATUS_PENDING,
        )
        self.client.force_login(self.department_head.user)

        response = self.client.get(reverse("schedule_planning", args=[year]), {"stage": "review"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sidebar_section"], "schedule_planning")
        self.assertEqual(response.context["selected_stage"], "review")
        self.assertContains(response, "Проверка отделов")
        self.assertContains(response, self.engineering.name)
        self.assertContains(response, 'data-sidebar-key="schedule-planning"')

    def test_enterprise_head_can_view_readiness_without_finish_action(self):
        year = self._year()
        self._start_collection()
        self.client.force_login(self.enterprise_head.user)

        response = self.client.get(reverse("preference_collection_readiness", args=[year]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Готовность сбора")
        self.assertNotContains(response, "Завершить сбор")

    def test_non_hr_and_non_enterprise_head_cannot_view_readiness(self):
        year = self._year()
        self._start_collection()

        self.client.force_login(self.employee.user)
        response = self.client.get(reverse("preference_collection_readiness", args=[year]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("calendar"))

        self.client.force_login(self.authorized_person.user)
        response = self.client.get(reverse("preference_collection_readiness", args=[year]))
        self.assertRedirects(response, reverse("applications"))

    def test_readiness_filters_and_search_use_employee_preference_state(self):
        year = self._year()
        self._start_collection()
        VacationPreference.objects.filter(employee=self.employee, year=year).delete()
        VacationPreference.objects.bulk_create(
            [
                VacationPreference(
                    employee=self.employee,
                    year=year,
                    priority=VacationPreference.PRIORITY_PRIMARY,
                    start_date=date(year, 6, 1),
                    end_date=date(year, 6, 14),
                    status=VacationPreference.STATUS_FILLED,
                    comment="Хочу летом.",
                ),
                VacationPreference(
                    employee=self.employee,
                    year=year,
                    priority=VacationPreference.PRIORITY_BACKUP,
                    start_date=date(year, 9, 1),
                    end_date=date(year, 9, 14),
                    status=VacationPreference.STATUS_FILLED,
                    comment="Хочу летом.",
                ),
            ]
        )
        VacationPreference.objects.filter(employee=self.department_head, year=year).delete()
        VacationPreference.objects.bulk_create(
            [
                VacationPreference(
                    employee=self.department_head,
                    year=year,
                    priority=VacationPreference.PRIORITY_PRIMARY,
                    status=VacationPreference.STATUS_SKIPPED,
                    comment="Пожеланий нет.",
                ),
                VacationPreference(
                    employee=self.department_head,
                    year=year,
                    priority=VacationPreference.PRIORITY_BACKUP,
                    status=VacationPreference.STATUS_SKIPPED,
                    comment="Пожеланий нет.",
                ),
            ]
        )
        self.client.force_login(self.hr_employee.user)

        filled_response = self.client.get(
            reverse("preference_collection_readiness", args=[year]),
            {"status": VacationPreference.STATUS_FILLED},
        )
        filled_ids = [row["employee"].id for row in filled_response.context["rows"]]
        self.assertIn(self.employee.id, filled_ids)
        self.assertNotIn(self.department_head.id, filled_ids)
        filled_row = next(row for row in filled_response.context["rows"] if row["employee"].id == self.employee.id)
        self.assertEqual(filled_row["role_variant"], "employee")
        self.assertEqual(filled_row["role_icon"], "person")

        skipped_response = self.client.get(
            reverse("preference_collection_readiness", args=[year]),
            {"status": VacationPreference.STATUS_SKIPPED},
        )
        skipped_ids = [row["employee"].id for row in skipped_response.context["rows"]]
        self.assertIn(self.department_head.id, skipped_ids)
        self.assertNotIn(self.employee.id, skipped_ids)

        pending_response = self.client.get(
            reverse("preference_collection_readiness", args=[year]),
            {"status": VacationPreference.STATUS_PENDING},
        )
        pending_ids = [row["employee"].id for row in pending_response.context["rows"]]
        self.assertNotIn(self.employee.id, pending_ids)
        self.assertNotIn(self.department_head.id, pending_ids)

        search_response = self.client.get(
            reverse("preference_collection_readiness", args=[year]),
            {"q": self.employee.last_name},
        )
        search_ids = [row["employee"].id for row in search_response.context["rows"]]
        self.assertIn(self.employee.id, search_ids)

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
        filled_policies = set(
            VacationPreference.objects.filter(
                year=year,
                status=VacationPreference.STATUS_FILLED,
                priority=VacationPreference.PRIORITY_PRIMARY,
            ).values_list("remainder_policy", flat=True)
        )
        self.assertIn(VacationPreference.REMAINDER_DEFER, filled_policies)
        self.assertIn(VacationPreference.REMAINDER_APPROVAL, filled_policies)
        self.assertIn(VacationPreference.REMAINDER_AUTO, filled_policies)
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
        self.assertEqual(summary["answered"], 0)
        self.assertEqual(summary["pending"], summary["total"])
        self.assertEqual(summary["not_answered"], summary["total"])
        self.assertEqual(summary["no_preferences"], 0)

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
        self.assertContains(response, "Доступно к планированию")
        self.assertContains(response, "Обязательно закрыть")
        self.assertContains(response, "К планированию")
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
        primary = VacationPreference.objects.get(
            employee=self.employee,
            year=year,
            priority=VacationPreference.PRIORITY_PRIMARY,
        )
        self.assertEqual(primary.remainder_policy, VacationPreference.REMAINDER_AUTO)
        notification = Notification.objects.get(
            dedupe_key=f"{Notification.TYPE_PREFERENCES_COLLECTION_STARTED}:{year}:{self.employee.id}"
        )
        self.assertEqual(notification.status, Notification.STATUS_DONE)

        saved_response = self.client.get(reverse("vacation_preferences", args=[year]))
        self.assertContains(saved_response, "Пожелания сохранены")
        self.assertContains(saved_response, "Можно изменить ответ до закрытия сбора.")
        self.assertContains(saved_response, "Изменить")
        self.assertNotContains(saved_response, "data-preferences-form")

        accidental_response = self.client.post(
            reverse("vacation_preferences", args=[year]),
            {
                "no_preferences": "on",
                "comment": "Даты не принципиальны.",
            },
        )

        self.assertEqual(accidental_response.status_code, 302)
        self.assertEqual(
            VacationPreference.objects.filter(
                employee=self.employee,
                year=year,
                status=VacationPreference.STATUS_FILLED,
            ).count(),
            2,
        )

        edit_response = self.client.get(f"{reverse('vacation_preferences', args=[year])}?edit=1")
        self.assertContains(edit_response, "data-preferences-form")
        self.assertContains(edit_response, "Сохранить изменения")
        self.assertContains(edit_response, "Отменить")
        self.assertContains(edit_response, f'value="{date(year, 6, 1).isoformat()}"')
        self.assertContains(edit_response, f'value="{date(year, 6, 14).isoformat()}"')
        self.assertContains(edit_response, f'value="{date(year, 8, 1).isoformat()}"')
        self.assertContains(edit_response, f'value="{date(year, 8, 14).isoformat()}"')

        response = self.client.post(
            reverse("vacation_preferences", args=[year]),
            {
                "editing": "1",
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

    def test_employee_can_submit_long_preference_within_balance(self):
        year = self._year()
        self._start_collection()
        self.employee.date_joined = date(year - 1, 1, 1)
        self.employee.annual_paid_leave_days = 52
        self.employee.save(update_fields=["date_joined", "annual_paid_leave_days"])
        self.client.force_login(self.employee.user)

        response = self.client.post(
            reverse("vacation_preferences", args=[year]),
            {
                "primary_start_date": date(year, 6, 1).isoformat(),
                "primary_end_date": date(year, 7, 23).isoformat(),
                "backup_start_date": date(year, 8, 1).isoformat(),
                "backup_end_date": date(year, 9, 22).isoformat(),
                "remainder_policy": VacationPreference.REMAINDER_APPROVAL,
                "comment": "Хочу использовать длинный отпуск.",
            },
        )

        self.assertEqual(response.status_code, 302)
        primary = VacationPreference.objects.get(
            employee=self.employee,
            year=year,
            priority=VacationPreference.PRIORITY_PRIMARY,
        )
        self.assertEqual(primary.start_date, date(year, 6, 1))
        self.assertEqual(primary.end_date, date(year, 7, 23))
        self.assertEqual(primary.remainder_policy, VacationPreference.REMAINDER_APPROVAL)

    def test_employee_cannot_submit_short_preference_when_balance_allows_normal_part(self):
        year = self._year()
        self._start_collection()
        self.client.force_login(self.employee.user)

        response = self.client.post(
            reverse("vacation_preferences", args=[year]),
            {
                "primary_start_date": date(year, 6, 1).isoformat(),
                "primary_end_date": date(year, 6, 6).isoformat(),
                "backup_start_date": date(year, 8, 1).isoformat(),
                "backup_end_date": date(year, 8, 14).isoformat(),
                "comment": "Хочу коротко.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Укажите не меньше 14 д.")
        self.assertFalse(
            VacationPreference.objects.filter(
                employee=self.employee,
                year=year,
                status=VacationPreference.STATUS_FILLED,
            ).exists()
        )

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
