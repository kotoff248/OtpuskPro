import calendar
from datetime import date, datetime

from django.utils import timezone
from django.utils.formats import date_format


NEW_HIRE_MONTHS = 6


def add_months_safe(value, months):
    total_months = (value.year * 12 + (value.month - 1)) + months
    target_year = total_months // 12
    target_month = total_months % 12 + 1
    last_day = calendar.monthrange(target_year, target_month)[1]
    return value.replace(year=target_year, month=target_month, day=min(value.day, last_day))


def normalize_date_value(value):
    if isinstance(value, str):
        return date.fromisoformat(value)
    return value.date() if isinstance(value, datetime) else value


def get_new_hire_available_from(employee):
    joined_date = normalize_date_value(getattr(employee, "date_joined", None))
    if joined_date is None:
        return None
    return add_months_safe(joined_date, NEW_HIRE_MONTHS)


def is_new_hire(employee, as_of=None):
    available_from = get_new_hire_available_from(employee)
    if available_from is None:
        return False
    as_of = normalize_date_value(as_of or timezone.localdate())
    return available_from > as_of


def build_new_hire_badge(employee, as_of=None):
    if not is_new_hire(employee, as_of=as_of):
        return None

    available_from = get_new_hire_available_from(employee)
    available_from_label = date_format(available_from, "j E Y", use_l10n=True)
    return {
        "label": "Новичок",
        "icon": "person_add",
        "icon_type": "material",
        "variant": "medium",
        "tooltip_title": "Новичок",
        "tooltip_text": f"Работает меньше 6 месяцев. Отпуск доступен после {available_from_label}.",
        "available_from": available_from.isoformat(),
    }
