from decimal import Decimal

from apps.leave.models import VacationRequest, VacationScheduleItem

ACTIVE_REQUEST_STATUSES = (
    VacationRequest.STATUS_PENDING,
    VacationRequest.STATUS_APPROVED,
)
CALENDAR_VISIBLE_STATUSES = (
    VacationRequest.STATUS_PENDING,
    VacationRequest.STATUS_APPROVED,
    VacationRequest.STATUS_REJECTED,
)
BALANCE_AFFECTING_TYPES = {"paid"}
SCHEDULE_BALANCE_STATUSES = (
    VacationScheduleItem.STATUS_PLANNED,
    VacationScheduleItem.STATUS_APPROVED,
)
SCHEDULE_STATUS_TO_CALENDAR_STATUS = {
    VacationScheduleItem.STATUS_DRAFT: VacationRequest.STATUS_PENDING,
    VacationScheduleItem.STATUS_PLANNED: VacationRequest.STATUS_PENDING,
    VacationScheduleItem.STATUS_APPROVED: VacationRequest.STATUS_APPROVED,
    VacationScheduleItem.STATUS_TRANSFERRED: VacationRequest.STATUS_APPROVED,
    VacationScheduleItem.STATUS_CANCELLED: VacationRequest.STATUS_REJECTED,
}
DISPLAY_FREE = "free"
DISPLAY_MIXED = "mixed"
DISPLAY_SCHEDULE_PLANNED = "schedule-planned"
DISPLAY_SCHEDULE_APPROVED = "schedule-approved"
DISPLAY_SCHEDULE_TRANSFERRED = "schedule-transferred"
DISPLAY_SCHEDULE_CANCELLED = "schedule-cancelled"
DISPLAY_REQUEST_PENDING = "request-pending"
DISPLAY_REQUEST_APPROVED = "request-approved"
DISPLAY_REQUEST_REJECTED = "request-rejected"

SCHEDULE_STATUS_TO_DISPLAY_STATUS = {
    VacationScheduleItem.STATUS_DRAFT: DISPLAY_SCHEDULE_PLANNED,
    VacationScheduleItem.STATUS_PLANNED: DISPLAY_SCHEDULE_PLANNED,
    VacationScheduleItem.STATUS_APPROVED: DISPLAY_SCHEDULE_APPROVED,
    VacationScheduleItem.STATUS_TRANSFERRED: DISPLAY_SCHEDULE_TRANSFERRED,
    VacationScheduleItem.STATUS_CANCELLED: DISPLAY_SCHEDULE_CANCELLED,
}
REQUEST_STATUS_TO_DISPLAY_STATUS = {
    VacationRequest.STATUS_PENDING: DISPLAY_REQUEST_PENDING,
    VacationRequest.STATUS_APPROVED: DISPLAY_REQUEST_APPROVED,
    VacationRequest.STATUS_REJECTED: DISPLAY_REQUEST_REJECTED,
}
DISPLAY_STATUS_UI = {
    DISPLAY_SCHEDULE_PLANNED: {
        "label": "Запланировано",
        "source_label": "Годовой график",
        "css_class": DISPLAY_SCHEDULE_PLANNED,
        "display_type": "schedule",
    },
    DISPLAY_SCHEDULE_APPROVED: {
        "label": "График утвержден",
        "source_label": "Годовой график",
        "css_class": DISPLAY_SCHEDULE_APPROVED,
        "display_type": "schedule",
    },
    DISPLAY_SCHEDULE_TRANSFERRED: {
        "label": "Перенесено",
        "source_label": "Перенос",
        "css_class": DISPLAY_SCHEDULE_TRANSFERRED,
        "display_type": "schedule",
    },
    DISPLAY_SCHEDULE_CANCELLED: {
        "label": "Отменено",
        "source_label": "Годовой график",
        "css_class": DISPLAY_SCHEDULE_CANCELLED,
        "display_type": "schedule",
    },
    DISPLAY_REQUEST_PENDING: {
        "label": "Заявка ожидает",
        "source_label": "Заявка",
        "css_class": DISPLAY_REQUEST_PENDING,
        "display_type": "request",
    },
    DISPLAY_REQUEST_APPROVED: {
        "label": "Внеплановая заявка одобрена",
        "source_label": "Заявка",
        "css_class": DISPLAY_REQUEST_APPROVED,
        "display_type": "request",
    },
    DISPLAY_REQUEST_REJECTED: {
        "label": "Заявка отклонена",
        "source_label": "Заявка",
        "css_class": DISPLAY_REQUEST_REJECTED,
        "display_type": "request",
    },
    DISPLAY_FREE: {"label": "Свободно", "source_label": "", "css_class": DISPLAY_FREE, "display_type": "free"},
    DISPLAY_MIXED: {
        "label": "Смешанный период",
        "source_label": "",
        "css_class": DISPLAY_MIXED,
        "display_type": "mixed",
    },
}
REQUEST_STATUS_UI = {
    VacationRequest.STATUS_APPROVED: {"label": "Одобрено", "icon": "check_circle", "css_class": "approved"},
    VacationRequest.STATUS_PENDING: {"label": "В ожидании", "icon": "watch_later", "css_class": "pending"},
    VacationRequest.STATUS_REJECTED: {"label": "Отклонено", "icon": "error", "css_class": "rejected"},
}
RUSSIAN_MONTH_NAMES = [
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
]
RUSSIAN_MONTH_SHORT_NAMES = [
    "Янв",
    "Фев",
    "Мар",
    "Апр",
    "Май",
    "Июн",
    "Июл",
    "Авг",
    "Сен",
    "Окт",
    "Ноя",
    "Дек",
]
VACATION_STATUS_META = {
    VacationRequest.STATUS_REJECTED: {"label": "Отклонено", "icon": "error"},
    VacationRequest.STATUS_APPROVED: {"label": "Одобрено", "icon": "check_circle"},
    VacationRequest.STATUS_PENDING: {"label": "В ожидании", "icon": "watch_later"},
    "free": {"label": "Свободно", "icon": "event_available"},
    "mixed": {"label": "Смешанный период", "icon": "layers"},
}
VACATION_STATUS_META.update(
    {
        display_status: {"label": meta["label"], "icon": "event"}
        for display_status, meta in DISPLAY_STATUS_UI.items()
    }
)
STATUS_PRIORITY = {
    "free": 0,
    VacationRequest.STATUS_REJECTED: 1,
    VacationRequest.STATUS_PENDING: 2,
    VacationRequest.STATUS_APPROVED: 3,
}
DISPLAY_STATUS_PRIORITY = {
    DISPLAY_FREE: 0,
    DISPLAY_SCHEDULE_CANCELLED: 1,
    DISPLAY_REQUEST_REJECTED: 2,
    DISPLAY_SCHEDULE_TRANSFERRED: 3,
    DISPLAY_REQUEST_PENDING: 4,
    DISPLAY_SCHEDULE_PLANNED: 5,
    DISPLAY_REQUEST_APPROVED: 6,
    DISPLAY_SCHEDULE_APPROVED: 7,
}
WEEKDAY_SHORT_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

LEAVE_DAY_QUANTIZER = Decimal("0.01")
LEAVE_ADVANCE_MONTHS = 6
