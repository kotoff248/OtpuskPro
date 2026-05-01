from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator
from django.db import models
from django.utils import timezone


class ProductionGroup(models.Model):
    department = models.ForeignKey(
        to="employees.Departments",
        on_delete=models.CASCADE,
        related_name="production_groups",
        verbose_name="Отдел",
    )
    name = models.CharField(max_length=120, verbose_name="Производственная группа")
    code = models.CharField(max_length=80, blank=True, default="", verbose_name="Код группы")
    description = models.TextField(blank=True, default="", verbose_name="Описание")

    class Meta:
        db_table = "employees_productiongroup"
        verbose_name = "Производственная группа"
        verbose_name_plural = "Производственные группы"
        ordering = ["department__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["department", "name"], name="unique_production_group_name_per_department"),
        ]

    def __str__(self):
        return f"{self.department}: {self.name}"


class EmployeePosition(models.Model):
    department = models.ForeignKey(
        to="employees.Departments",
        on_delete=models.CASCADE,
        related_name="employee_positions",
        verbose_name="Отдел",
    )
    production_group = models.ForeignKey(
        to="employees.ProductionGroup",
        on_delete=models.PROTECT,
        related_name="positions",
        verbose_name="Производственная группа",
    )
    title = models.CharField(max_length=120, verbose_name="Должность")
    is_active = models.BooleanField(default=True, verbose_name="Активна")

    class Meta:
        db_table = "employees_employeeposition"
        verbose_name = "Должность"
        verbose_name_plural = "Должности"
        ordering = ["department__name", "production_group__name", "title"]
        constraints = [
            models.UniqueConstraint(fields=["department", "title"], name="unique_position_title_per_department"),
        ]

    def __str__(self):
        return f"{self.title} ({self.department})"


class DepartmentCoverageRule(models.Model):
    department = models.ForeignKey(
        to="employees.Departments",
        on_delete=models.CASCADE,
        related_name="coverage_rules",
        verbose_name="Отдел",
    )
    production_group = models.ForeignKey(
        to="employees.ProductionGroup",
        on_delete=models.CASCADE,
        related_name="coverage_rules",
        verbose_name="Производственная группа",
    )
    min_staff_required = models.PositiveSmallIntegerField(default=1, verbose_name="Минимум должно остаться")
    max_absent = models.PositiveSmallIntegerField(default=1, verbose_name="Максимум отсутствующих")
    criticality_level = models.PositiveSmallIntegerField(default=3, verbose_name="Критичность")

    class Meta:
        db_table = "employees_departmentcoveragerule"
        verbose_name = "Правило покрытия"
        verbose_name_plural = "Правила покрытия"
        ordering = ["department__name", "production_group__name"]
        constraints = [
            models.UniqueConstraint(fields=["department", "production_group"], name="unique_coverage_rule_per_group"),
            models.CheckConstraint(
                check=models.Q(criticality_level__gte=1, criticality_level__lte=5),
                name="coverage_rule_criticality_1_5",
            ),
        ]

    def __str__(self):
        return f"{self.department}: {self.production_group}"


class ProductionGroupSubstitutionRule(models.Model):
    department = models.ForeignKey(
        to="employees.Departments",
        on_delete=models.CASCADE,
        related_name="substitution_rules",
        verbose_name="Отдел",
    )
    source_group = models.ForeignKey(
        to="employees.ProductionGroup",
        on_delete=models.CASCADE,
        related_name="substitution_sources",
        verbose_name="Кого замещают",
    )
    substitute_group = models.ForeignKey(
        to="employees.ProductionGroup",
        on_delete=models.CASCADE,
        related_name="substitution_targets",
        verbose_name="Кто замещает",
    )
    max_covered_absences = models.PositiveSmallIntegerField(default=1, verbose_name="Закрывает отсутствующих")

    class Meta:
        db_table = "employees_productiongroupsubstitutionrule"
        verbose_name = "Правило замещения"
        verbose_name_plural = "Правила замещения"
        ordering = ["department__name", "source_group__name", "substitute_group__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["department", "source_group", "substitute_group"],
                name="unique_production_group_substitution",
            ),
        ]

    def __str__(self):
        return f"{self.department}: {self.substitute_group} -> {self.source_group}"


class Employees(models.Model):
    ROLE_EMPLOYEE = "employee"
    ROLE_HR = "hr"
    ROLE_DEPARTMENT_HEAD = "department_head"
    ROLE_ENTERPRISE_HEAD = "enterprise_head"
    ROLE_AUTHORIZED_PERSON = "authorized_person"

    ROLE_CHOICES = [
        (ROLE_EMPLOYEE, "Сотрудник"),
        (ROLE_HR, "HR"),
        (ROLE_DEPARTMENT_HEAD, "Руководитель отдела"),
        (ROLE_ENTERPRISE_HEAD, "Руководитель предприятия"),
        (ROLE_AUTHORIZED_PERSON, "Уполномоченное лицо"),
    ]
    MANAGEMENT_ROLES = {
        ROLE_HR,
        ROLE_DEPARTMENT_HEAD,
        ROLE_ENTERPRISE_HEAD,
    }
    SERVICE_ROLES = {
        ROLE_AUTHORIZED_PERSON,
    }
    EDITABLE_ROLE_CHOICES = [
        (ROLE_EMPLOYEE, "Сотрудник"),
        (ROLE_HR, "HR"),
        (ROLE_DEPARTMENT_HEAD, "Руководитель отдела"),
        (ROLE_ENTERPRISE_HEAD, "Руководитель предприятия"),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_profile",
    )
    last_name = models.CharField(max_length=100, default="", verbose_name="Фамилия")
    first_name = models.CharField(max_length=100, default="", verbose_name="Имя")
    middle_name = models.CharField(max_length=100, default="", verbose_name="Отчество")
    login = models.CharField(max_length=150, unique=True, verbose_name="Логин")
    position = models.CharField(max_length=100, verbose_name="Должность")
    employee_position = models.ForeignKey(
        to="employees.EmployeePosition",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
        verbose_name="Должность из справочника",
    )
    role = models.CharField(
        max_length=32,
        choices=ROLE_CHOICES,
        default=ROLE_EMPLOYEE,
        verbose_name="Роль в системе",
    )
    date_joined = models.DateField(verbose_name="Дата начала работы", default=timezone.localdate)
    annual_paid_leave_days = models.PositiveIntegerField(
        verbose_name="Годовая норма оплачиваемого отпуска",
        default=52,
        validators=[MaxValueValidator(52)],
    )
    manual_leave_adjustment_days = models.IntegerField(
        verbose_name="Ручная корректировка отпускного баланса",
        default=0,
    )
    is_active_employee = models.BooleanField(default=True, verbose_name="Активный сотрудник")
    department = models.ForeignKey(
        to="employees.Departments",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Отдел",
        related_name="employees",
    )
    is_manager = models.BooleanField(default=False, verbose_name="Руководитель")
    is_enterprise_deputy = models.BooleanField(default=False, verbose_name="Заместитель руководителя предприятия")

    class Meta:
        db_table = "employees_employees"
        verbose_name = "Сотрудник"
        verbose_name_plural = "Сотрудники"

    @property
    def full_name(self):
        return " ".join(part for part in [self.last_name, self.first_name, self.middle_name] if part).strip()

    @property
    def is_management(self):
        return self.role in self.MANAGEMENT_ROLES

    @property
    def is_service_account(self):
        return self.role in self.SERVICE_ROLES

    def save(self, *args, **kwargs):
        if self.is_service_account:
            self.last_name = ""
            self.first_name = ""
            self.middle_name = ""
            self.position = ""
            self.employee_position = None
            self.department = None
            self.annual_paid_leave_days = 0
            self.is_enterprise_deputy = False
        elif self.employee_position_id:
            self.position = self.employee_position.title
        self.is_manager = self.is_management
        super().save(*args, **kwargs)

    def __str__(self):
        return self.full_name or self.login


class Departments(models.Model):
    name = models.CharField(max_length=150, unique=True, verbose_name="Название отдела")
    head = models.OneToOneField(
        to="employees.Employees",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_department",
        verbose_name="Руководитель отдела",
    )
    deputy = models.OneToOneField(
        to="employees.Employees",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deputy_department",
        verbose_name="Заместитель руководителя отдела",
    )
    date_added = models.DateTimeField(default=timezone.now, verbose_name="Дата добавления")

    class Meta:
        db_table = "employees_departments"
        verbose_name = "Отдел"
        verbose_name_plural = "Отделы"

    def __str__(self):
        return self.name
