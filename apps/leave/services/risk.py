from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.employees.models import Employees
from apps.leave.models import VacationRequest

from .dates import get_vacation_day_cost, quantize_leave_days
from .ledger import get_employee_requestable_leave, get_employee_reserved_paid_days, get_employee_used_paid_days
from .staffing import (
    build_department_staffing_context,
    evaluate_department_staffing_state,
    evaluate_enterprise_leadership_state,
    format_staff_count as _format_staff_count,
    get_active_absence_employee_ids,
    get_department_staffing_rule,
    get_enterprise_leadership_employee_ids,
    get_weighted_department_workload,
)


RISK_LABELS = dict(VacationRequest.RISK_CHOICES)


def _risk_label_for_level(risk_level):
    return RISK_LABELS.get(risk_level, "Низкий")


def _risk_level_for_score(risk_score):
    if risk_score >= 70:
        return VacationRequest.RISK_HIGH
    if risk_score >= 40:
        return VacationRequest.RISK_MEDIUM
    return VacationRequest.RISK_LOW


def _load_risk_boost(load_level):
    return {
        1: 0,
        2: 4,
        3: 8,
        4: 14,
        5: 20,
    }.get(load_level, 8)


def _overlap_risk_boost(overlapping_absences_count):
    if overlapping_absences_count <= 0:
        return 0
    if overlapping_absences_count <= 3:
        return overlapping_absences_count * 5
    return min(24, 15 + (overlapping_absences_count - 3) * 3)


def _criticality_risk_boost(criticality_level, *, step=4):
    return max(0, criticality_level - 3) * step


def _risk_detail(kind, severity, title, text, **metadata):
    return {
        "kind": kind,
        "severity": severity,
        "title": title,
        "text": text,
        **metadata,
    }


def _build_risk_explanation(
    *,
    risk_score,
    risk_level,
    details,
    department,
    affected_group_name,
    remaining_staff_count,
    min_staff_required,
    substitution_used,
    department_load_level,
    overlapping_absences_count,
):
    severity_priority = {"conflict": 0, "high": 1, "medium": 2, "info": 3}
    normalized_details = [
        {key: value for key, value in detail.items() if key != "affected_employee_ids"}
        for detail in sorted(
            details,
            key=lambda detail: (
                severity_priority.get(detail.get("severity"), 9),
                detail.get("title", ""),
                detail.get("text", ""),
            ),
        )
    ]
    is_conflict = any(detail.get("severity") == "conflict" for detail in normalized_details)
    if normalized_details:
        short_reason = normalized_details[0]["text"]
    elif risk_level == VacationRequest.RISK_LOW:
        short_reason = "Критичных пересечений не найдено."
    else:
        short_reason = f"Риск {_risk_label_for_level(risk_level).lower()}: учтены загрузка отдела и пересечения отпусков."

    if is_conflict:
        recommended_action = "Сначала перенесите период или скорректируйте правила состава, затем возвращайтесь к согласованию."
    elif substitution_used:
        recommended_action = "Проверьте, что замещение действительно доступно на весь период отпуска."
    elif risk_level == VacationRequest.RISK_HIGH:
        recommended_action = "Лучше подобрать другой период или отдельно подтвердить решение у руководителя."
    elif risk_level == VacationRequest.RISK_MEDIUM:
        recommended_action = "Можно согласовывать после проверки загрузки отдела и пересечений."
    else:
        recommended_action = "Период можно согласовывать по обычному маршруту."

    return {
        "level": risk_level,
        "label": _risk_label_for_level(risk_level),
        "score": risk_score,
        "is_conflict": is_conflict,
        "short_reason": short_reason,
        "details": normalized_details,
        "affected_department": department.name if department else "",
        "affected_group": affected_group_name or "",
        "remaining_staff": remaining_staff_count,
        "required_staff": min_staff_required,
        "substitution_used": substitution_used,
        "department_load_level": department_load_level,
        "overlapping_absences_count": overlapping_absences_count,
        "recommended_action": recommended_action,
    }


def _calculate_vacation_request_risk(
    employee,
    start_date,
    end_date,
    vacation_type,
    exclude_request_id=None,
    exclude_schedule_item_id=None,
    *,
    include_explanation=False,
):
    requested_cost = Decimal(get_vacation_day_cost(vacation_type, start_date, end_date))
    requestable_days = get_employee_requestable_leave(employee, start_date)
    if vacation_type == "paid":
        try:
            used_days = Decimal(get_employee_used_paid_days(employee, start_date))
            reserved_days = Decimal(
                get_employee_reserved_paid_days(
                    employee,
                    start_date,
                    exclude_request_id=exclude_request_id,
                    exclude_schedule_item_id=exclude_schedule_item_id,
                )
            )
        except ValidationError:
            used_days = Decimal("0")
            reserved_days = requestable_days + Decimal(employee.manual_leave_adjustment_days)
    else:
        used_days = Decimal("0")
        reserved_days = Decimal("0")
    balance_after_request = quantize_leave_days(
        requestable_days
        + Decimal(employee.manual_leave_adjustment_days)
        - used_days
        - reserved_days
        - requested_cost
    )

    department = employee.department
    staffing_rule = get_department_staffing_rule(department)
    if department is not None:
        weighted_workload = get_weighted_department_workload(department, start_date, end_date, staffing_rule)
    else:
        weighted_workload = {
            "department_load_level": 1,
            "min_staff_required": staffing_rule.min_staff_required if staffing_rule else 0,
            "max_absent": staffing_rule.max_absent if staffing_rule else 1,
        }
    department_load_level = weighted_workload["department_load_level"]
    min_staff_required = weighted_workload["min_staff_required"]

    if department is None:
        risk_payload = {
            "risk_score": 25,
            "risk_level": VacationRequest.RISK_LOW,
            "department_load_level": department_load_level,
            "overlapping_absences_count": 0,
            "remaining_staff_count": 0,
            "min_staff_required": min_staff_required,
            "balance_after_request": balance_after_request,
        }
        if include_explanation:
            risk_payload["risk_explanation"] = _build_risk_explanation(
                risk_score=risk_payload["risk_score"],
                risk_level=risk_payload["risk_level"],
                details=[
                    _risk_detail(
                        "missing_department",
                        "info",
                        "Отдел не указан",
                        "Отдел сотрудника не указан, поэтому проверка состава ограничена балансом и датами.",
                    )
                ],
                department=None,
                affected_group_name="",
                remaining_staff_count=0,
                min_staff_required=min_staff_required,
                substitution_used=False,
                department_load_level=department_load_level,
                overlapping_absences_count=0,
            )
        return risk_payload

    department_staffing = build_department_staffing_context(department, end_date)
    department_employee_ids = department_staffing["staff_ids"]
    overlapping_employee_ids = get_active_absence_employee_ids(
        employee_ids=department_employee_ids,
        start_date=start_date,
        end_date=end_date,
        exclude_request_id=exclude_request_id,
        exclude_schedule_item_id=exclude_schedule_item_id,
    ) - {employee.id}
    overlapping_absences_count = len(overlapping_employee_ids)

    employee_group = (
        employee.employee_position.production_group
        if getattr(employee, "employee_position_id", None) and employee.employee_position
        else None
    )
    staffing_evaluation = evaluate_department_staffing_state(
        department_staffing,
        set(overlapping_employee_ids) | {employee.id},
        min_staff_required=min_staff_required,
        max_absent=weighted_workload["max_absent"],
        target_group_id=employee_group.id if employee_group else None,
        target_employee_id=employee.id,
    )

    remaining_staff_count = staffing_evaluation["remaining_staff_count"]
    min_staff_required = staffing_evaluation["min_staff_required"]
    details = list(staffing_evaluation["issues"])
    hard_conflict = staffing_evaluation["hard_conflict"]
    substitution_used = staffing_evaluation["substitution_used"]
    affected_group_name = staffing_evaluation["affected_group_name"] or (employee_group.name if employee_group else "")
    leadership_boost = staffing_evaluation["leadership_boost"]
    staffing_boost = staffing_evaluation["staffing_boost"]
    group_staffing_boost = staffing_evaluation["group_staffing_boost"]

    if employee.role == Employees.ROLE_ENTERPRISE_HEAD or employee.is_enterprise_deputy:
        enterprise_head_ids, enterprise_deputy_ids = get_enterprise_leadership_employee_ids(end_date)
        enterprise_absence_ids = get_active_absence_employee_ids(
            employee_ids=enterprise_head_ids | enterprise_deputy_ids,
            start_date=start_date,
            end_date=end_date,
            exclude_request_id=exclude_request_id,
            exclude_schedule_item_id=exclude_schedule_item_id,
        )
        enterprise_evaluation = evaluate_enterprise_leadership_state(
            enterprise_absence_ids | {employee.id},
            end_date,
            target_employee=employee,
        )
        if enterprise_evaluation["hard_conflict"]:
            hard_conflict = True
            leadership_boost += enterprise_evaluation["leadership_boost"]
            details.extend(enterprise_evaluation["issues"])

    criticality_level = staffing_rule.criticality_level if staffing_rule else 3
    role_boost = 10 if employee.role == Employees.ROLE_DEPARTMENT_HEAD else 0
    balance_boost = 18 if vacation_type == "paid" and balance_after_request < 0 else 0
    if balance_boost:
        details.append(
            _risk_detail(
                "negative_balance",
                "high",
                "Недостаточно дней",
                "После заявки оплачиваемый баланс уйдет в отрицательное значение.",
                balance_after_request=float(balance_after_request),
            )
        )
    if department_load_level >= 4:
        details.append(
            _risk_detail(
                "department_load",
                "medium",
                "Повышенная загрузка",
                f"Нагрузка отдела на период оценивается как {department_load_level}/5.",
                affected_department=department.name,
                department_load_level=department_load_level,
            )
        )
    if overlapping_absences_count:
        details.append(
            _risk_detail(
                "overlapping_absences",
                "info",
                "Есть пересечения",
                f"В этот период уже отсутствуют {_format_staff_count(overlapping_absences_count)}.",
                affected_department=department.name,
                overlapping_absences_count=overlapping_absences_count,
            )
        )

    risk_score = min(
        95,
        10
        + _load_risk_boost(department_load_level)
        + _overlap_risk_boost(overlapping_absences_count)
        + _criticality_risk_boost(criticality_level)
        + role_boost
        + leadership_boost
        + staffing_boost
        + group_staffing_boost
        + balance_boost,
    )
    if hard_conflict:
        risk_score = max(risk_score, 72)
    risk_level = _risk_level_for_score(risk_score)

    risk_payload = {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "department_load_level": department_load_level,
        "overlapping_absences_count": overlapping_absences_count,
        "remaining_staff_count": remaining_staff_count,
        "min_staff_required": min_staff_required,
        "balance_after_request": balance_after_request,
    }
    if include_explanation:
        risk_payload["risk_explanation"] = _build_risk_explanation(
            risk_score=risk_score,
            risk_level=risk_level,
            details=details,
            department=department,
            affected_group_name=affected_group_name,
            remaining_staff_count=remaining_staff_count,
            min_staff_required=min_staff_required,
            substitution_used=substitution_used,
            department_load_level=department_load_level,
            overlapping_absences_count=overlapping_absences_count,
        )
    return risk_payload


def calculate_vacation_request_risk(
    employee,
    start_date,
    end_date,
    vacation_type,
    exclude_request_id=None,
    exclude_schedule_item_id=None,
):
    return _calculate_vacation_request_risk(
        employee,
        start_date,
        end_date,
        vacation_type,
        exclude_request_id=exclude_request_id,
        exclude_schedule_item_id=exclude_schedule_item_id,
    )


def build_vacation_request_risk_explanation(
    employee,
    start_date,
    end_date,
    vacation_type,
    exclude_request_id=None,
    exclude_schedule_item_id=None,
):
    return _calculate_vacation_request_risk(
        employee,
        start_date,
        end_date,
        vacation_type,
        exclude_request_id=exclude_request_id,
        exclude_schedule_item_id=exclude_schedule_item_id,
        include_explanation=True,
    )["risk_explanation"]


def build_saved_vacation_risk_explanation(vacation):
    details = []
    department = vacation.employee.department if getattr(vacation, "employee_id", None) else None
    remaining_staff_count = int(vacation.remaining_staff_count or 0)
    min_staff_required = int(vacation.min_staff_required or 0)
    overlapping_absences_count = int(vacation.overlapping_absences_count or 0)
    department_load_level = int(vacation.department_load_level or 1)

    if min_staff_required and remaining_staff_count < min_staff_required:
        details.append(
            _risk_detail(
                "department_staff_shortage",
                "conflict",
                "Недостаток состава отдела",
                (
                    f"По сохраненному расчету в отделе останется {_format_staff_count(remaining_staff_count)} "
                    f"при минимуме {_format_staff_count(min_staff_required)}."
                ),
                affected_department=department.name if department else "",
                remaining_staff=remaining_staff_count,
                required_staff=min_staff_required,
            )
        )
    elif min_staff_required and remaining_staff_count == min_staff_required:
        details.append(
            _risk_detail(
                "department_staff_minimum_reached",
                "medium",
                "Отдел на минимуме",
                f"По сохраненному расчету отдел остается ровно на минимуме: {_format_staff_count(min_staff_required)}.",
                affected_department=department.name if department else "",
                remaining_staff=remaining_staff_count,
                required_staff=min_staff_required,
            )
        )

    if department_load_level >= 4:
        details.append(
            _risk_detail(
                "department_load",
                "medium",
                "Повышенная загрузка",
                f"Нагрузка отдела на момент расчета оценивалась как {department_load_level}/5.",
                affected_department=department.name if department else "",
                department_load_level=department_load_level,
            )
        )

    if overlapping_absences_count:
        details.append(
            _risk_detail(
                "overlapping_absences",
                "info",
                "Есть пересечения",
                f"На момент расчета в этот период уже отсутствовали {_format_staff_count(overlapping_absences_count)}.",
                affected_department=department.name if department else "",
                overlapping_absences_count=overlapping_absences_count,
            )
        )

    balance_after_request = getattr(vacation, "balance_after_request", 0)
    if getattr(vacation, "vacation_type", "") == "paid" and balance_after_request < 0:
        details.append(
            _risk_detail(
                "negative_balance",
                "high",
                "Недостаточно дней",
                "По сохраненному расчету оплачиваемый баланс уходит в отрицательное значение.",
                balance_after_request=float(balance_after_request),
            )
        )

    return _build_risk_explanation(
        risk_score=int(vacation.risk_score or 0),
        risk_level=vacation.risk_level,
        details=details,
        department=department,
        affected_group_name=(
            vacation.employee.employee_position.production_group.name
            if getattr(vacation.employee, "employee_position_id", None)
            and getattr(vacation.employee, "employee_position", None)
            and vacation.employee.employee_position.production_group
            else ""
        ),
        remaining_staff_count=remaining_staff_count,
        min_staff_required=min_staff_required,
        substitution_used=False,
        department_load_level=department_load_level,
        overlapping_absences_count=overlapping_absences_count,
    )


def build_vacation_object_risk_explanation(vacation):
    return build_vacation_request_risk_explanation(
        vacation.employee,
        vacation.start_date,
        vacation.end_date,
        vacation.vacation_type,
        exclude_request_id=vacation.id,
    )


def build_saved_schedule_change_risk_explanation(change_request):
    details = []
    department = change_request.employee.department if getattr(change_request, "employee_id", None) else None
    remaining_staff_count = int(change_request.remaining_staff_count or 0)
    min_staff_required = int(change_request.min_staff_required or 0)
    overlapping_absences_count = int(change_request.overlapping_absences_count or 0)
    department_load_level = int(change_request.department_load_level or 1)

    if min_staff_required and remaining_staff_count < min_staff_required:
        details.append(
            _risk_detail(
                "department_staff_shortage",
                "conflict",
                "Недостаток состава отдела",
                (
                    f"По сохраненному расчету в отделе останется {_format_staff_count(remaining_staff_count)} "
                    f"при минимуме {_format_staff_count(min_staff_required)}."
                ),
                affected_department=department.name if department else "",
                remaining_staff=remaining_staff_count,
                required_staff=min_staff_required,
            )
        )
    elif min_staff_required and remaining_staff_count == min_staff_required:
        details.append(
            _risk_detail(
                "department_staff_minimum_reached",
                "medium",
                "Отдел на минимуме",
                f"По сохраненному расчету отдел остается ровно на минимуме: {_format_staff_count(min_staff_required)}.",
                affected_department=department.name if department else "",
                remaining_staff=remaining_staff_count,
                required_staff=min_staff_required,
            )
        )

    if department_load_level >= 4:
        details.append(
            _risk_detail(
                "department_load",
                "medium",
                "Повышенная загрузка",
                f"Нагрузка отдела на момент расчета оценивалась как {department_load_level}/5.",
                affected_department=department.name if department else "",
                department_load_level=department_load_level,
            )
        )

    if overlapping_absences_count:
        details.append(
            _risk_detail(
                "overlapping_absences",
                "info",
                "Есть пересечения",
                f"На момент расчета в этот период уже отсутствовали {_format_staff_count(overlapping_absences_count)}.",
                affected_department=department.name if department else "",
                overlapping_absences_count=overlapping_absences_count,
            )
        )

    return _build_risk_explanation(
        risk_score=int(change_request.risk_score or 0),
        risk_level=change_request.risk_level,
        details=details,
        department=department,
        affected_group_name=(
            change_request.employee.employee_position.production_group.name
            if getattr(change_request.employee, "employee_position_id", None)
            and getattr(change_request.employee, "employee_position", None)
            and change_request.employee.employee_position.production_group
            else ""
        ),
        remaining_staff_count=remaining_staff_count,
        min_staff_required=min_staff_required,
        substitution_used=False,
        department_load_level=department_load_level,
        overlapping_absences_count=overlapping_absences_count,
    )


def build_schedule_change_risk_explanation(change_request):
    return build_vacation_request_risk_explanation(
        change_request.employee,
        change_request.new_start_date,
        change_request.new_end_date,
        change_request.schedule_item.vacation_type,
        exclude_schedule_item_id=change_request.schedule_item_id,
    )

def calculate_schedule_change_risk(schedule_item, new_start_date, new_end_date):
    risk_payload = calculate_vacation_request_risk(
        schedule_item.employee,
        new_start_date,
        new_end_date,
        schedule_item.vacation_type,
        exclude_schedule_item_id=schedule_item.id,
    )
    return {
        "risk_score": risk_payload["risk_score"],
        "risk_level": risk_payload["risk_level"],
        "department_load_level": risk_payload["department_load_level"],
        "overlapping_absences_count": risk_payload["overlapping_absences_count"],
        "remaining_staff_count": risk_payload["remaining_staff_count"],
        "min_staff_required": risk_payload["min_staff_required"],
        "balance_after_change": risk_payload["balance_after_request"],
    }
