from dataclasses import dataclass

from apps.employees.models import Departments, Employees


VACATION_APPROVER_ROLE_LABELS = {
    Employees.ROLE_DEPARTMENT_HEAD: "Руководитель отдела",
    Employees.ROLE_ENTERPRISE_HEAD: "Руководитель предприятия",
    Employees.ROLE_AUTHORIZED_PERSON: "Уполномоченное лицо",
}


@dataclass(frozen=True)
class VacationApprovalRoute:
    role: str
    role_label: str
    employee: Employees | None
    reason: str


def get_vacation_approval_role_label(role):
    return VACATION_APPROVER_ROLE_LABELS.get(role, "Не определён")


def _get_department_head(employee):
    if not employee.department_id:
        return None

    head_id = (
        Departments.objects.filter(pk=employee.department_id)
        .values_list("head_id", flat=True)
        .first()
    )
    if head_id:
        head = (
            Employees.objects.filter(
                pk=head_id,
                role=Employees.ROLE_DEPARTMENT_HEAD,
                is_active_employee=True,
            )
            .exclude(pk=employee.pk)
            .first()
        )
        if head is not None:
            return head

    return (
        Employees.objects.filter(
            role=Employees.ROLE_DEPARTMENT_HEAD,
            department_id=employee.department_id,
            is_active_employee=True,
        )
        .exclude(pk=employee.pk)
        .order_by("last_name", "first_name", "id")
        .first()
    )


def _get_enterprise_head():
    return (
        Employees.objects.filter(role=Employees.ROLE_ENTERPRISE_HEAD, is_active_employee=True)
        .order_by("last_name", "first_name", "id")
        .first()
    )


def _get_authorized_person():
    return (
        Employees.objects.filter(role=Employees.ROLE_AUTHORIZED_PERSON, is_active_employee=True)
        .order_by("id")
        .first()
    )


def get_expected_vacation_approver(employee):
    if employee is None:
        return VacationApprovalRoute(
            role="",
            role_label=get_vacation_approval_role_label(""),
            employee=None,
            reason="Для заявки не указан сотрудник.",
        )

    if employee.role == Employees.ROLE_EMPLOYEE:
        return VacationApprovalRoute(
            role=Employees.ROLE_DEPARTMENT_HEAD,
            role_label=get_vacation_approval_role_label(Employees.ROLE_DEPARTMENT_HEAD),
            employee=_get_department_head(employee),
            reason="Обычную заявку сотрудника согласует руководитель его отдела.",
        )

    if employee.role in {Employees.ROLE_HR, Employees.ROLE_DEPARTMENT_HEAD}:
        return VacationApprovalRoute(
            role=Employees.ROLE_ENTERPRISE_HEAD,
            role_label=get_vacation_approval_role_label(Employees.ROLE_ENTERPRISE_HEAD),
            employee=_get_enterprise_head(),
            reason="Заявки HR и руководителей отделов переходят на уровень руководителя предприятия.",
        )

    if employee.role == Employees.ROLE_ENTERPRISE_HEAD:
        return VacationApprovalRoute(
            role=Employees.ROLE_AUTHORIZED_PERSON,
            role_label=get_vacation_approval_role_label(Employees.ROLE_AUTHORIZED_PERSON),
            employee=_get_authorized_person(),
            reason="Заявку руководителя предприятия согласует уполномоченное лицо.",
        )

    return VacationApprovalRoute(
        role="",
        role_label=get_vacation_approval_role_label(""),
        employee=None,
        reason="Для этой роли маршрут согласования не задан.",
    )
