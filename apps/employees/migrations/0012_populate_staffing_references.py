from django.db import migrations


def _infer_group_name(position):
    position_lower = (position or "").lower()
    if "руковод" in position_lower or "начальник" in position_lower:
        return "Руководство отдела"
    if "hr" in position_lower or "кадр" in position_lower:
        return "HR и кадровое сопровождение"
    if any(keyword in position_lower for keyword in ["механик", "слесарь", "ремонт", "электромонтер", "диагност"]):
        return "Механики и ремонт"
    if any(keyword in position_lower for keyword in ["инженер", "технолог", "качество", "эколог", "рискам", "охране"]):
        return "Инженеры"
    if any(keyword in position_lower for keyword in ["логист", "диспетчер", "постав", "склад", "цепоч"]):
        return "Логистика"
    if any(keyword in position_lower for keyword in ["финанс", "эконом", "закуп", "бухгалтер", "контракт"]):
        return "Финансы и закупки"
    if any(keyword in position_lower for keyword in ["мастер", "машинист", "оператор", "линии"]):
        return "Производственная смена"
    if any(keyword in position_lower for keyword in ["безопас", "инспектор"]):
        return "Безопасность"
    return "Общая группа"


def populate_staffing_references(apps, schema_editor):
    Employees = apps.get_model("employees", "Employees")
    Departments = apps.get_model("employees", "Departments")
    ProductionGroup = apps.get_model("employees", "ProductionGroup")
    EmployeePosition = apps.get_model("employees", "EmployeePosition")
    DepartmentCoverageRule = apps.get_model("employees", "DepartmentCoverageRule")
    service_roles = {"authorized_person"}

    for employee in Employees.objects.filter(department_id__isnull=False).exclude(role__in=service_roles):
        title = (employee.position or "").strip() or "Не указана"
        group_name = _infer_group_name(title)
        group, _ = ProductionGroup.objects.get_or_create(
            department_id=employee.department_id,
            name=group_name,
            defaults={
                "code": group_name.lower().replace(" ", "-"),
                "description": "Создано миграцией из текущих должностей сотрудников.",
            },
        )
        position, _ = EmployeePosition.objects.get_or_create(
            department_id=employee.department_id,
            title=title,
            defaults={"production_group_id": group.id},
        )
        if employee.employee_position_id != position.id or employee.position != position.title:
            employee.employee_position_id = position.id
            employee.position = position.title
            employee.save(update_fields=["employee_position", "position"])

    for department in Departments.objects.all():
        groups = list(ProductionGroup.objects.filter(department=department).order_by("name"))
        for group in groups:
            employee_count = Employees.objects.filter(
                department=department,
                employee_position__production_group=group,
                is_active_employee=True,
            ).exclude(role__in=service_roles).count()
            if group.name == "Руководство отдела":
                min_staff_required = 0
                max_absent = 1
                criticality_level = 5
            else:
                min_staff_required = max(1, round(employee_count * 0.55)) if employee_count else 1
                max_absent = max(1, employee_count - min_staff_required) if employee_count else 1
                criticality_level = 4 if group.name != "Общая группа" else 3
            DepartmentCoverageRule.objects.get_or_create(
                department=department,
                production_group=group,
                defaults={
                    "min_staff_required": min_staff_required,
                    "max_absent": max_absent,
                    "criticality_level": criticality_level,
                },
            )

        if department.head_id and not department.deputy_id:
            deputy = Employees.objects.filter(
                department=department,
                is_active_employee=True,
            ).exclude(role__in=service_roles).exclude(id=department.head_id).order_by("date_joined", "last_name").first()
            if deputy is not None:
                department.deputy_id = deputy.id
                department.save(update_fields=["deputy"])

    if not Employees.objects.filter(is_enterprise_deputy=True).exists():
        deputy = Employees.objects.filter(role="hr", is_active_employee=True).order_by("date_joined", "last_name").first()
        if deputy is not None:
            deputy.is_enterprise_deputy = True
            deputy.save(update_fields=["is_enterprise_deputy"])


def noop_reverse(apps, schema_editor):
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("employees", "0011_staffing_rules"),
    ]

    operations = [
        migrations.RunPython(populate_staffing_references, noop_reverse),
    ]
