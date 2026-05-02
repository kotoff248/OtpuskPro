# Work Summary For Continuing Kabinet.pro

Updated: 2026-05-01

## How To Continue In A New Chat

Start by reading:

1. `AGENTS.md`
2. this file
3. `git status --short`

The workspace is:

`D:\Fedya\Инст\МАГИСТЕРСКАЯ\Kabinet.pro`

The project is `Kabinet.pro`, a Django 5 manager cabinet for vacation planning,
approvals, staffing visibility, department workload, risks, analytics and future
AI-assisted schedule recommendations.

Do not revert unrelated dirty files. The worktree is expected to be dirty because
many UI/domain changes were implemented during the current development thread.

## Current Product Direction

The system is moving from a simple vacation request tracker toward a workforce
planning tool for managers.

The central idea now:

- yearly vacation schedule is the main planning object;
- requests and transfers are documents around that schedule;
- risk/conflict logic should explain whether a vacation can be approved safely;
- staffing rules should be realistic enough for a dissertation demo;
- AI/generator will later recommend a yearly schedule, but the rule layer must
  be understandable and testable first.

## Recent Major Work Completed

### UI Pages

The following pages were heavily redesigned and are now visually close to the
target system style:

- `/employees/` employees list;
- `/applications/` request/transfer approval board;
- `/departments/` departments;
- `/main/` and `/employee/<id>/` employee profile;
- `/calendar/` vacation schedule;
- `/staffing/` staffing rules.

Important frontend patterns:

- authenticated links should use `data-app-link` / `window.KabinetNavigation`;
- large panels should follow the shared dark panel/card style;
- employee role icons are used consistently:
  - employee: `person`;
  - HR: `manage_accounts`;
  - department head: `admin_panel_settings`;
  - enterprise head: crown symbol;
- role color variants are used across employees, applications and calendar.

### Employee Profile

Profile is now sectioned:

- `Сводка сотрудника`;
- `Отпуска и график`;
- `История заявок`.

The balance explanation is inline in the summary, not a modal:

- `Баланс по рабочим годам`;
- working year cards;
- future empty working years are hidden unless they are used/reserved.

`Отпуска и график` is the archive of confirmed/planned absences:

- annual schedule items;
- approved paid/unpaid/study requests;
- schedule transfers when present;
- filters by year/all and vacation type.

### Calendar

The vacation calendar now has:

- month/year modes;
- search by employee;
- department filter;
- issue filter: `Все / Риски / Конфликты`;
- compact legend popover;
- year totals row by month;
- employee cards aligned with the employees/applications style;
- drawer with employee details, entries, profile link, request link, transfer action and show-in-calendar action;
- risk/conflict icons on cards and totals.

Year rows were stabilized:

- no square year-cell JS sizing;
- month/year employee cards share a stable row height;
- switching month/year should preserve the visible employee area.

## Staffing Rules And Smart Conflicts

This is the newest domain layer and should be treated as version 1.1, not final.

Implemented models:

- `ProductionGroup`
- `EmployeePosition`
- `DepartmentCoverageRule`
- `ProductionGroupSubstitutionRule`

Employee/department additions:

- `Employees.employee_position`
- `Employees.is_enterprise_deputy`
- `Departments.deputy`

Old text `Employees.position` remains as a display/cache field for compatibility.
Employee forms use a select for position from the reference table.

The `/staffing/` page manages:

- production groups;
- positions;
- coverage rules;
- substitution rules;
- department deputies.

Access direction:

- HR and enterprise head edit;
- department head should view own department rules without broad editing.

## Current Conflict Logic

Conflicts are no longer only "too many people absent from department".

Calendar conflict detection now considers:

- department minimum staff;
- department maximum absences;
- production group minimum staff;
- production group maximum absences;
- allowed substitution between production groups;
- substitution capacity: `max_covered_absences`;
- free capacity of the substitute group after its own minimum is preserved;
- department head + deputy absence at the same time;
- enterprise head + enterprise deputy absence at the same time.

Important behavior:

- if a group is below minimum and no substitute can cover it -> conflict;
- if substitute covers the shortage -> high risk, not conflict;
- if group max absent is exceeded -> conflict;
- department-wide rules remain as a safety net, but group/deputy reasons should
  be the primary meaningful explanation.

## Risk Formula Current State

The risk formula was softened because almost all requests were becoming high
risk.

Main changes in `apps/leave/services/risk.py`:

- paid vacation is no longer automatically penalized;
- department load is a soft background boost;
- overlaps are capped and no longer explode linearly;
- department head role boost was reduced;
- real staffing shortage remains strong;
- group shortage remains strong;
- substitution coverage gives high risk, not conflict;
- being exactly on a limit gives a smaller warning boost;
- thresholds still are:
  - low: `< 40`;
  - medium: `40-69`;
  - high: `>= 70`.

The seed schedule risk was softened in
`apps/core/management/commands/seed_vacation_requests.py`.

After rebuilding demo DB on 2026-05-01:

- active/non-rejected requests: 96
- request risks: 17 low, 47 medium, 32 high
- future requests: 25
- future request risks: 3 low, 19 medium, 3 high
- active schedule items: 1109
- schedule item risks: 768 low, 341 medium, 0 high

This is acceptable for demo: high risk exists, but it is no longer everywhere.

## Demo Data / Seeder

The seed command was updated to create realistic staffing data:

- explicit production groups per department;
- positions tied to groups;
- coverage rules;
- directional substitutions;
- department deputies;
- enterprise deputy.

The demo DB was rebuilt with:

```powershell
.\.venv\Scripts\python.exe manage.py seed_vacation_requests --confirm-reset
```

Last output:

- departments: 5
- department heads: 5
- HR: 2
- enterprise heads: 1
- regular employees: 100
- requests: approved=72, pending=24, rejected=13

Default generated password is `1234`.

## Tests Last Run

These passed after the latest changes:

```powershell
.\.venv\Scripts\python.exe manage.py test apps.employees apps.leave apps.core --keepdb
.\.venv\Scripts\python.exe manage.py check
```

Also passed targeted seed/request tests during the risk work.

## Current Discussion To Continue

The next design question is how to show the new risk/conflict explanation across
the whole system, not just on one page.

## Notifications V1.2

The notification center now covers request approvals, schedule transfers,
manager schedule changes, and upcoming vacation reminders.

Operational commands:

```powershell
.\.venv\Scripts\python.exe manage.py backfill_notifications
.\.venv\Scripts\python.exe manage.py send_upcoming_vacation_reminders --days-before 7
```

Backfill restores notifications from existing DB history and marks historical
results as read so the sidebar counter is not flooded. Managed approval tasks
are completed by approve/reject business actions, not by the manual
`Выполнено` button.

Recommended principle:

- calendar and request detail show concrete problem and full explanation;
- request creation shows the warning before submit;
- applications page shows short reason for approver;
- departments and analytics show aggregate risk picture;
- employees/profile show only compact status so cards do not become heavy;
- staffing page explains where rules come from.

Recommended next implementation step:

Build one reusable "risk explanation" layer/service, then render it differently
per page.

Suggested pages:

1. `/calendar/`
   - keep icons;
   - drawer should show full reason:
     - missing group;
     - used substitution;
     - department near/below limit;
     - head and deputy absent.

2. Request creation modal/form
   - show risk before submit;
   - show "why";
   - for high risk, suggest choosing another period.

3. `/applications/`
   - cards show short reason;
   - detail page shows full reason for approval decision.

4. `/departments/`
   - department cards show upcoming staffing pressure:
     - groups near shortage;
     - conflicts in next month;
     - absences now/soon.

5. `/employees/` and `/employee/<id>/`
   - only compact status:
     - no schedule;
     - schedule ok;
     - has risk;
     - has conflict.

6. `/analytics/`
   - aggregate planning analytics:
     - peak months;
     - risky departments;
     - weak production groups;
     - employees without planned vacation;
     - overload forecast.

7. `/staffing/`
   - improve clarity of rules:
     - group capacity;
     - current headcount;
     - reserve;
     - who can substitute whom and how many.

## Next Recommended Feature Plan

Implement "Risk Explanation V1":

- create a service that returns normalized explanation objects:
  - `level`;
  - `score`;
  - `is_conflict`;
  - `short_reason`;
  - `details`;
  - `affected_department`;
  - `affected_group`;
  - `remaining_staff`;
  - `required_staff`;
  - `substitution_used`;
  - `recommended_action`;
- use it in:
  - calendar drawer;
  - vacation request preview;
  - application cards/detail;
  - department summary;
- write tests for:
  - calm request -> low risk with calm explanation;
  - group shortage -> conflict explanation;
  - substitution -> high risk explanation, not conflict;
  - leadership pair absence -> conflict explanation.

Do not add a neural module yet. First make deterministic rules explainable.

## Important Commands

Run checks:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test apps.accounts apps.employees apps.leave apps.core --keepdb
```

Run demo seed:

```powershell
.\.venv\Scripts\python.exe manage.py seed_vacation_requests --confirm-reset
```

Run local server through helper:

```powershell
.\scripts\django_server.ps1 -Action restart -Port 8001 -ReadyTimeoutSeconds 10
.\scripts\django_server.ps1 -Action status -Port 8001
.\scripts\django_server.ps1 -Action stop -Port 8001
```
