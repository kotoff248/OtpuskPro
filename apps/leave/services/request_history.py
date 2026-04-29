from datetime import timedelta

from django.utils import timezone

from apps.leave.models import VacationRequest, VacationRequestHistory


HISTORY_TEXT = {
    VacationRequestHistory.ACTION_CREATED: (
        "Заявка создана",
        "Сотрудник сформировал заявку на отпуск.",
    ),
    VacationRequestHistory.ACTION_SUBMITTED: (
        "Отправлена на согласование",
        "Система направила заявку по маршруту согласования.",
    ),
    VacationRequestHistory.ACTION_APPROVED: (
        "Заявка одобрена",
        "Согласующий подтвердил отпуск.",
    ),
    VacationRequestHistory.ACTION_REJECTED: (
        "Заявка отклонена",
        "Согласующий отклонил отпуск.",
    ),
    VacationRequestHistory.ACTION_DELETED: (
        "Заявка удалена",
        "Заявка удалена из активного списка.",
    ),
}


def create_vacation_request_history(
    vacation,
    action,
    *,
    actor=None,
    title="",
    description="",
    status_snapshot=None,
    created_at=None,
):
    default_title, default_description = HISTORY_TEXT[action]
    return VacationRequestHistory.objects.create(
        vacation_request=vacation,
        employee=vacation.employee,
        actor=actor,
        action=action,
        title=title or default_title,
        description=description or default_description,
        status_snapshot=status_snapshot if status_snapshot is not None else vacation.status,
        created_at=created_at or timezone.now(),
    )


def get_vacation_submitted_at(created_at, reviewed_at=None):
    submitted_at = created_at + timedelta(minutes=30)
    if reviewed_at is not None and submitted_at >= reviewed_at:
        submitted_at = created_at + ((reviewed_at - created_at) / 2)
    return submitted_at


def record_vacation_request_created(vacation, *, created_at=None, submitted_at=None):
    created_at = created_at or vacation.created_at or timezone.now()
    submitted_at = submitted_at or created_at
    create_vacation_request_history(
        vacation,
        VacationRequestHistory.ACTION_CREATED,
        actor=vacation.employee,
        status_snapshot=VacationRequest.STATUS_PENDING,
        created_at=created_at,
    )
    create_vacation_request_history(
        vacation,
        VacationRequestHistory.ACTION_SUBMITTED,
        actor=vacation.employee,
        status_snapshot=VacationRequest.STATUS_PENDING,
        created_at=submitted_at,
    )


def record_vacation_request_reviewed(vacation):
    action = (
        VacationRequestHistory.ACTION_APPROVED
        if vacation.status == VacationRequest.STATUS_APPROVED
        else VacationRequestHistory.ACTION_REJECTED
    )
    create_vacation_request_history(
        vacation,
        action,
        actor=vacation.reviewed_by,
        created_at=vacation.reviewed_at,
    )


def record_vacation_request_deleted(vacation, *, actor):
    create_vacation_request_history(
        vacation,
        VacationRequestHistory.ACTION_DELETED,
        actor=actor,
        description="Заявка удалена до рассмотрения.",
    )


def rebuild_vacation_request_history(vacation, *, created_at=None, submitted_at=None, reviewed_at=None):
    created_at = created_at or vacation.created_at or timezone.now()
    reviewed_at = reviewed_at if reviewed_at is not None else vacation.reviewed_at
    submitted_at = submitted_at or get_vacation_submitted_at(created_at, reviewed_at)

    VacationRequestHistory.objects.filter(vacation_request=vacation).delete()
    record_vacation_request_created(vacation, created_at=created_at, submitted_at=submitted_at)
    if vacation.status in {VacationRequest.STATUS_APPROVED, VacationRequest.STATUS_REJECTED}:
        create_vacation_request_history(
            vacation,
            (
                VacationRequestHistory.ACTION_APPROVED
                if vacation.status == VacationRequest.STATUS_APPROVED
                else VacationRequestHistory.ACTION_REJECTED
            ),
            actor=vacation.reviewed_by,
            status_snapshot=vacation.status,
            created_at=reviewed_at or submitted_at,
        )


def _entry_payload(entry):
    return {
        "title": entry.title,
        "description": entry.description,
        "created_at": entry.created_at,
        "actor": entry.actor,
        "action": entry.action,
    }


def _legacy_vacation_request_history(vacation):
    created_at = vacation.created_at
    entries = [
        {
            "title": "Заявка создана",
            "description": "Сотрудник сформировал заявку на отпуск.",
            "created_at": created_at,
            "actor": vacation.employee,
            "action": VacationRequestHistory.ACTION_CREATED,
        },
        {
            "title": "Отправлена на согласование",
            "description": "Система направила заявку по маршруту согласования.",
            "created_at": created_at,
            "actor": vacation.employee,
            "action": VacationRequestHistory.ACTION_SUBMITTED,
        },
    ]
    if vacation.status == VacationRequest.STATUS_PENDING:
        entries.append(
            {
                "title": "Ожидает решения",
                "description": "Заявка находится на маршруте согласования.",
                "created_at": created_at,
                "actor": None,
                "action": VacationRequestHistory.ACTION_SUBMITTED,
            }
        )
    elif vacation.reviewed_at:
        entries.append(
            {
                "title": "Заявка одобрена" if vacation.status == VacationRequest.STATUS_APPROVED else "Заявка отклонена",
                "description": "Согласующий принял решение по заявке.",
                "created_at": vacation.reviewed_at,
                "actor": vacation.reviewed_by,
                "action": (
                    VacationRequestHistory.ACTION_APPROVED
                    if vacation.status == VacationRequest.STATUS_APPROVED
                    else VacationRequestHistory.ACTION_REJECTED
                ),
            }
        )
    return entries


def get_vacation_request_history(vacation):
    entries = list(
        VacationRequestHistory.objects.filter(vacation_request=vacation)
        .select_related("actor")
        .order_by("created_at", "id")
    )
    if entries:
        return [_entry_payload(entry) for entry in entries]
    return _legacy_vacation_request_history(vacation)
