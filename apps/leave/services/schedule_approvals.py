from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.accounts.services import (
    get_managed_department_id,
    is_department_head_employee,
    is_enterprise_head_employee,
    is_hr_employee,
)
from apps.core.models import Notification
from apps.core.services.notifications import mark_notifications_done_by_dedupe_prefix
from apps.employees.models import Employees
from apps.leave.models import (
    VacationSchedule,
    VacationScheduleDepartmentApproval,
    VacationScheduleEnterpriseApproval,
    VacationScheduleItem,
)

from .notifications import (
    notify_schedule_department_review,
    notify_schedule_department_rework_required,
    notify_schedule_approved,
    notify_schedule_enterprise_returned,
    notify_schedule_enterprise_review,
)
from .planning_cycles import is_active_planning_year
from .schedule_auto_place_jobs import get_active_schedule_auto_place_job
from apps.leave.services.schedule_drafts.page_context import (
    build_schedule_draft_summary_context,
    has_department_schedule_hard_conflicts,
)


def _department_review_notification_prefix(approval):
    return f"{Notification.TYPE_SCHEDULE_REVIEW_REQUESTED}:department:{approval.schedule_id}:{approval.department_id}"


def _department_rework_notification_prefix(approval):
    return f"{Notification.TYPE_SCHEDULE_REVIEW_REQUESTED}:department_rework:{approval.schedule_id}:{approval.department_id}:"


def _enterprise_review_notification_prefix(schedule_or_approval):
    schedule_id = getattr(schedule_or_approval, "schedule_id", None) or schedule_or_approval.id
    return f"{Notification.TYPE_SCHEDULE_REVIEW_REQUESTED}:enterprise:{schedule_id}:"


def _enterprise_rework_notification_prefix(schedule_or_approval):
    schedule_id = getattr(schedule_or_approval, "schedule_id", None) or schedule_or_approval.id
    return f"{Notification.TYPE_SCHEDULE_REVIEW_REQUESTED}:enterprise_rework:{schedule_id}:"


def _department_head_for_review(department):
    head = getattr(department, "head", None)
    if (
        head is not None
        and head.role == Employees.ROLE_DEPARTMENT_HEAD
        and getattr(head, "is_active_employee", True)
    ):
        return head
    return (
        Employees.objects.filter(role=Employees.ROLE_DEPARTMENT_HEAD, is_active_employee=True)
        .filter(Q(managed_department=department) | Q(department=department))
        .order_by("id")
        .first()
    )


def _enterprise_head_for_review():
    return (
        Employees.objects.filter(role=Employees.ROLE_ENTERPRISE_HEAD, is_active_employee=True)
        .order_by("id")
        .first()
    )


def _draft_review_departments(schedule):
    departments = []
    seen_ids = set()
    draft_items = (
        VacationScheduleItem.objects.select_related("employee__department", "employee__department__head")
        .filter(
            schedule=schedule,
            status=VacationScheduleItem.STATUS_DRAFT,
            employee__is_active_employee=True,
            employee__department__isnull=False,
        )
        .order_by("employee__department__name", "employee__department_id")
    )
    for item in draft_items:
        department = item.employee.department
        if department.id in seen_ids:
            continue
        departments.append(department)
        seen_ids.add(department.id)
    return departments


def _review_start_block_reason_for_summary(draft_summary):
    reasons = []
    manual_count = int(draft_summary.get("manual") or 0)
    blocking_count = int(draft_summary.get("blocking") or 0)
    conflict_count = int(draft_summary.get("conflicts") or 0)

    if manual_count:
        reasons.append(f"остались ручные строки: {manual_count}")
    if blocking_count:
        reasons.append(f"есть срочные остатки: {blocking_count}")
    if conflict_count:
        reasons.append(f"есть hard-конфликты: {conflict_count}")

    if not reasons:
        return ""
    return "Нельзя отправить на проверку отделов: " + "; ".join(reasons) + "."


def _department_review_state(schedule):
    approvals = list(
        VacationScheduleDepartmentApproval.objects.select_related("department")
        .filter(schedule=schedule)
        .order_by("department__name", "department_id")
    )
    total = len(approvals)
    approved = sum(1 for approval in approvals if approval.status == VacationScheduleDepartmentApproval.STATUS_APPROVED)
    pending = sum(1 for approval in approvals if approval.status == VacationScheduleDepartmentApproval.STATUS_PENDING)
    rejected = sum(1 for approval in approvals if approval.status == VacationScheduleDepartmentApproval.STATUS_REJECTED)
    return {
        "approvals": approvals,
        "total": total,
        "approved": approved,
        "pending": pending,
        "rejected": rejected,
    }


def _schedule_has_final_hard_conflicts(schedule, approvals=None):
    approvals = approvals if approvals is not None else VacationScheduleDepartmentApproval.objects.filter(schedule=schedule)
    return any(has_department_schedule_hard_conflicts(schedule, approval.department_id) for approval in approvals)


def _enterprise_review_block_reason(schedule):
    if schedule is None:
        return "График за этот год не найден."
    if schedule.status == VacationSchedule.STATUS_APPROVED:
        return "График уже утверждён."
    if schedule.status != VacationSchedule.STATUS_DEPARTMENT_REVIEW:
        return "Финальное утверждение доступно только после проверки отделов."

    review_state = _department_review_state(schedule)
    if not review_state["total"]:
        return "Сначала отправьте черновик на проверку отделов."
    if review_state["pending"]:
        return f"Не все отделы согласовали график: ожидают {review_state['pending']}."
    if review_state["rejected"]:
        return f"Есть возвращённые отделы: {review_state['rejected']}."
    if review_state["approved"] != review_state["total"]:
        return "Дождитесь согласования всех отделов."
    if _schedule_has_final_hard_conflicts(schedule, review_state["approvals"]):
        return "В графике остались hard-конфликты. Исправьте их перед финальным утверждением."
    if _enterprise_head_for_review() is None:
        return "Назначьте активного руководителя предприятия."

    enterprise_approval = VacationScheduleEnterpriseApproval.objects.filter(schedule=schedule).first()
    if enterprise_approval is not None and enterprise_approval.status == VacationScheduleEnterpriseApproval.STATUS_PENDING:
        return "График уже отправлен руководителю предприятия."
    if enterprise_approval is not None and enterprise_approval.status == VacationScheduleEnterpriseApproval.STATUS_REJECTED:
        if enterprise_approval.approved_at is None:
            return "Сначала выберите отдел для доработки после финального возврата."
        has_new_department_approval = VacationScheduleDepartmentApproval.objects.filter(
            schedule=schedule,
            status=VacationScheduleDepartmentApproval.STATUS_APPROVED,
            approved_at__gt=enterprise_approval.approved_at,
        ).exists()
        if not has_new_department_approval:
            return "Сначала доработайте выбранный отдел и повторно согласуйте его у руководителя отдела."
    return ""


def _validate_schedule_ready_for_department_review(schedule, *, year, actor):
    if not is_hr_employee(actor):
        raise ValidationError("Отправить график на проверку отделов может только HR.")
    if schedule is None:
        raise ValidationError("Черновик графика за этот год не найден.")
    if schedule.status == VacationSchedule.STATUS_DEPARTMENT_REVIEW:
        raise ValidationError("График уже отправлен на проверку отделов.")
    if schedule.status != VacationSchedule.STATUS_DRAFT:
        raise ValidationError("На проверку можно отправить только черновик графика.")

    active_job = get_active_schedule_auto_place_job(year=year, schedule=schedule)
    if active_job is not None:
        raise ValidationError("Дождитесь завершения действия «Добрать незакрытые дни».")

    draft_context = build_schedule_draft_summary_context(year, actor=actor)
    draft_summary = draft_context["draft_summary"]
    block_reason = _review_start_block_reason_for_summary(draft_summary)
    if block_reason:
        raise ValidationError(block_reason)

    departments = _draft_review_departments(schedule)
    if not departments:
        raise ValidationError("В черновике нет отделов с пунктами графика для проверки.")

    missing_heads = [department.name for department in departments if _department_head_for_review(department) is None]
    if missing_heads:
        raise ValidationError("Назначьте руководителя для отделов: " + ", ".join(missing_heads) + ".")

    return departments, draft_summary


def get_schedule_department_review_start_state(year, actor):
    if not is_hr_employee(actor):
        return {
            "can_start": False,
            "reason": "Отправить график на проверку отделов может только HR.",
        }
    if not is_active_planning_year(year):
        return {
            "can_start": False,
            "reason": "Отправить график на проверку можно только для активного планового года.",
        }

    schedule = VacationSchedule.objects.filter(year=year).first()
    if schedule is None:
        return {"can_start": False, "reason": "Черновик графика за этот год не найден."}
    if schedule.status == VacationSchedule.STATUS_DEPARTMENT_REVIEW:
        return {"can_start": False, "reason": "График уже отправлен на проверку отделов."}
    if schedule.status != VacationSchedule.STATUS_DRAFT:
        return {"can_start": False, "reason": "На проверку можно отправить только черновик графика."}

    active_job = get_active_schedule_auto_place_job(year=year, schedule=schedule)
    if active_job is not None:
        return {
            "can_start": False,
            "reason": "Дождитесь завершения действия «Добрать незакрытые дни».",
        }

    draft_context = build_schedule_draft_summary_context(year, actor=actor)
    block_reason = _review_start_block_reason_for_summary(draft_context["draft_summary"])
    if block_reason:
        return {"can_start": False, "reason": block_reason}

    departments = _draft_review_departments(schedule)
    if not departments:
        return {
            "can_start": False,
            "reason": "В черновике нет отделов с пунктами графика для проверки.",
        }

    missing_heads = [department.name for department in departments if _department_head_for_review(department) is None]
    if missing_heads:
        return {
            "can_start": False,
            "reason": "Назначьте руководителя для отделов: " + ", ".join(missing_heads) + ".",
        }

    return {
        "can_start": True,
        "reason": "",
        "departments_count": len(departments),
    }


def get_schedule_enterprise_review_start_state(year, actor):
    if not is_hr_employee(actor):
        return {
            "can_start": False,
            "reason": "Отправить график на финальное утверждение может только HR.",
        }
    if not is_active_planning_year(year):
        return {
            "can_start": False,
            "reason": "Отправить график на финальное утверждение можно только для активного планового года.",
        }

    schedule = VacationSchedule.objects.filter(year=year).first()
    reason = _enterprise_review_block_reason(schedule)
    if reason:
        return {"can_start": False, "reason": reason}
    return {"can_start": True, "reason": ""}


@transaction.atomic
def submit_schedule_for_department_review(year, actor):
    if not is_active_planning_year(year):
        raise ValidationError("Отправить график на проверку можно только для активного планового года.")
    schedule = (
        VacationSchedule.objects.select_for_update()
        .filter(year=year)
        .first()
    )
    departments, draft_summary = _validate_schedule_ready_for_department_review(schedule, year=year, actor=actor)

    planned_items_count = VacationScheduleItem.objects.filter(
        schedule=schedule,
        status=VacationScheduleItem.STATUS_DRAFT,
    ).update(status=VacationScheduleItem.STATUS_PLANNED)

    schedule.status = VacationSchedule.STATUS_DEPARTMENT_REVIEW
    schedule.save(update_fields=["status"])

    approvals = []
    for department in departments:
        head = _department_head_for_review(department)
        approval, _ = VacationScheduleDepartmentApproval.objects.update_or_create(
            schedule=schedule,
            department=department,
            defaults={
                "department_head": head,
                "status": VacationScheduleDepartmentApproval.STATUS_PENDING,
                "comment": "",
                "approved_at": None,
            },
        )
        approvals.append(approval)
        notify_schedule_department_review(schedule, approval, actor=actor)

    return {
        "schedule": schedule,
        "departments_count": len(approvals),
        "planned_items_count": planned_items_count,
        "manual_count": draft_summary.get("manual", 0),
    }


@transaction.atomic
def submit_schedule_for_enterprise_review(year, actor):
    if not is_hr_employee(actor):
        raise ValidationError("Отправить график на финальное утверждение может только HR.")
    if not is_active_planning_year(year):
        raise ValidationError("Отправить график на финальное утверждение можно только для активного планового года.")

    schedule = VacationSchedule.objects.select_for_update().filter(year=year).first()
    reason = _enterprise_review_block_reason(schedule)
    if reason:
        raise ValidationError(reason)

    enterprise_head = _enterprise_head_for_review()
    if enterprise_head is None:
        raise ValidationError("Назначьте активного руководителя предприятия.")

    approval, _ = VacationScheduleEnterpriseApproval.objects.update_or_create(
        schedule=schedule,
        defaults={
            "enterprise_head": enterprise_head,
            "status": VacationScheduleEnterpriseApproval.STATUS_PENDING,
            "comment": "",
            "approved_at": None,
        },
    )
    mark_notifications_done_by_dedupe_prefix(_enterprise_rework_notification_prefix(schedule))
    notify_schedule_enterprise_review(
        schedule,
        approval,
        actor=actor,
        dedupe_marker=f"submit:{timezone.now().strftime('%Y%m%d%H%M%S')}",
    )
    return approval


def can_review_schedule_department_approval(actor, approval):
    if not is_department_head_employee(actor) or approval is None:
        return False
    managed_department_id = get_managed_department_id(actor)
    return bool(managed_department_id and managed_department_id == approval.department_id)


def can_review_schedule_enterprise_approval(actor, approval):
    if not is_enterprise_head_employee(actor) or approval is None:
        return False
    return approval.enterprise_head_id == actor.id


def _get_department_approval_for_update(approval_id, actor):
    approval = (
        VacationScheduleDepartmentApproval.objects.select_for_update()
        .select_related("schedule", "department")
        .filter(id=approval_id)
        .first()
    )
    if approval is None:
        raise ValidationError("Согласование отдела не найдено.")
    if not can_review_schedule_department_approval(actor, approval):
        raise ValidationError("Вы не можете согласовать график за этот отдел.")
    if approval.schedule.status != VacationSchedule.STATUS_DEPARTMENT_REVIEW:
        raise ValidationError("График сейчас не находится на проверке отделов.")
    if approval.status != VacationScheduleDepartmentApproval.STATUS_PENDING:
        raise ValidationError("По этому отделу решение уже принято.")
    return approval


@transaction.atomic
def approve_schedule_department_review(approval_id, actor, comment=""):
    approval = _get_department_approval_for_update(approval_id, actor)
    approval.status = VacationScheduleDepartmentApproval.STATUS_APPROVED
    approval.comment = (comment or "").strip()
    approval.approved_at = timezone.now()
    approval.save(update_fields=["status", "comment", "approved_at"])
    mark_notifications_done_by_dedupe_prefix(_department_review_notification_prefix(approval))
    return approval


@transaction.atomic
def return_schedule_department_review(approval_id, actor, comment):
    comment = (comment or "").strip()
    if not comment:
        raise ValidationError("Укажите комментарий, что нужно доработать.")

    approval = _get_department_approval_for_update(approval_id, actor)
    approval.status = VacationScheduleDepartmentApproval.STATUS_REJECTED
    approval.comment = comment
    approval.approved_at = timezone.now()
    approval.save(update_fields=["status", "comment", "approved_at"])
    mark_notifications_done_by_dedupe_prefix(_department_review_notification_prefix(approval))
    notify_schedule_department_rework_required(approval.schedule, approval, actor=actor)
    return approval


@transaction.atomic
def resubmit_schedule_department_review(approval_id, actor):
    if not is_hr_employee(actor):
        raise ValidationError("Повторно отправить отдел на проверку может только HR.")

    approval = (
        VacationScheduleDepartmentApproval.objects.select_for_update()
        .select_related("schedule", "department")
        .filter(id=approval_id)
        .first()
    )
    if approval is None:
        raise ValidationError("Согласование отдела не найдено.")
    if approval.schedule.status != VacationSchedule.STATUS_DEPARTMENT_REVIEW:
        raise ValidationError("График сейчас не находится на проверке отделов.")
    if approval.status != VacationScheduleDepartmentApproval.STATUS_REJECTED:
        raise ValidationError("Повторно отправить можно только возвращённый отдел.")
    if has_department_schedule_hard_conflicts(approval.schedule, approval.department_id):
        raise ValidationError("В отделе остались hard-конфликты. Исправьте график перед повторной отправкой.")

    approval.status = VacationScheduleDepartmentApproval.STATUS_PENDING
    approval.approved_at = None
    approval.save(update_fields=["status", "approved_at"])
    mark_notifications_done_by_dedupe_prefix(_department_rework_notification_prefix(approval))
    notify_schedule_department_review(
        approval.schedule,
        approval,
        actor=actor,
        dedupe_marker=f"resubmit:{timezone.now().strftime('%Y%m%d%H%M%S')}",
    )
    return approval


def _get_enterprise_approval_for_update(approval_id, actor):
    approval = (
        VacationScheduleEnterpriseApproval.objects.select_for_update()
        .select_related("schedule")
        .filter(id=approval_id)
        .first()
    )
    if approval is None:
        raise ValidationError("Финальное согласование графика не найдено.")
    if not can_review_schedule_enterprise_approval(actor, approval):
        raise ValidationError("Вы не можете финально согласовать этот график.")
    if approval.schedule.status != VacationSchedule.STATUS_DEPARTMENT_REVIEW:
        raise ValidationError("График сейчас не находится на финальном согласовании.")
    if approval.status != VacationScheduleEnterpriseApproval.STATUS_PENDING:
        raise ValidationError("По этому графику финальное решение уже принято.")
    return approval


@transaction.atomic
def approve_schedule_enterprise_review(approval_id, actor, comment=""):
    approval = _get_enterprise_approval_for_update(approval_id, actor)
    reason = _enterprise_review_block_reason(approval.schedule)
    if reason and reason != "График уже отправлен руководителю предприятия.":
        raise ValidationError(reason)

    now = timezone.now()
    approval.status = VacationScheduleEnterpriseApproval.STATUS_APPROVED
    approval.comment = (comment or "").strip()
    approval.approved_at = now
    approval.save(update_fields=["status", "comment", "approved_at"])

    schedule = approval.schedule
    schedule.status = VacationSchedule.STATUS_APPROVED
    schedule.approved_by = actor
    schedule.approved_at = now
    schedule.save(update_fields=["status", "approved_by", "approved_at"])

    VacationScheduleItem.objects.filter(
        schedule=schedule,
        status=VacationScheduleItem.STATUS_PLANNED,
    ).update(status=VacationScheduleItem.STATUS_APPROVED)

    mark_notifications_done_by_dedupe_prefix(_enterprise_review_notification_prefix(approval))
    notify_schedule_approved(schedule, actor=actor)
    return approval


@transaction.atomic
def return_schedule_enterprise_review(approval_id, actor, comment):
    comment = (comment or "").strip()
    if not comment:
        raise ValidationError("Укажите комментарий, что нужно доработать.")

    approval = _get_enterprise_approval_for_update(approval_id, actor)
    approval.status = VacationScheduleEnterpriseApproval.STATUS_REJECTED
    approval.comment = comment
    approval.approved_at = timezone.now()
    approval.save(update_fields=["status", "comment", "approved_at"])

    mark_notifications_done_by_dedupe_prefix(_enterprise_review_notification_prefix(approval))
    notify_schedule_enterprise_returned(approval.schedule, approval, actor=actor)
    return approval


@transaction.atomic
def open_department_rework_from_enterprise_return(approval_id, department_id, actor):
    if not is_hr_employee(actor):
        raise ValidationError("Открыть доработку отдела после финального возврата может только HR.")

    enterprise_approval = (
        VacationScheduleEnterpriseApproval.objects.select_for_update()
        .select_related("schedule")
        .filter(id=approval_id)
        .first()
    )
    if enterprise_approval is None:
        raise ValidationError("Финальное согласование графика не найдено.")
    if enterprise_approval.schedule.status != VacationSchedule.STATUS_DEPARTMENT_REVIEW:
        raise ValidationError("График сейчас не находится на согласовании.")
    if enterprise_approval.status != VacationScheduleEnterpriseApproval.STATUS_REJECTED:
        raise ValidationError("Открыть доработку можно только после возврата руководителем предприятия.")

    department_approval = (
        VacationScheduleDepartmentApproval.objects.select_for_update()
        .select_related("schedule", "department")
        .filter(schedule=enterprise_approval.schedule, department_id=department_id)
        .first()
    )
    if department_approval is None:
        raise ValidationError("Согласование выбранного отдела не найдено.")

    comment_prefix = "Возврат руководителя предприятия"
    department_approval.status = VacationScheduleDepartmentApproval.STATUS_REJECTED
    department_approval.comment = (
        f"{comment_prefix}: {enterprise_approval.comment}"
        if enterprise_approval.comment
        else comment_prefix
    )
    department_approval.approved_at = timezone.now()
    department_approval.save(update_fields=["status", "comment", "approved_at"])

    mark_notifications_done_by_dedupe_prefix(_enterprise_rework_notification_prefix(enterprise_approval))
    return department_approval


def schedule_department_review_url(schedule):
    return f'{reverse("schedule_planning", args=[schedule.year])}?stage=review'
