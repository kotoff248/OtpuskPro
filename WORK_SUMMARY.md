# Work Summary For Continuing In Codex

## Project

Django project for the vacation management / executive dashboard system.

Workspace path on the original machine:

`D:\Fedya\Инст\ДИПЛОМ\Inst\Website`

Main idea of the system:

- Cabinet for enterprise management and HR.
- Vacation requests, employee profiles, vacation calendar, analytics.
- Target domain: Norilsk / Far North conditions.
- Annual paid leave norm: 52 calendar days = 28 basic days + 24 Far North additional days.

## What Was Implemented Earlier

### Service account `admin_1`

`admin_1` is now a clean service account for approving the enterprise head vacation.

It should not appear as a normal employee:

- no employee card;
- no full name;
- no position;
- no department;
- cannot be edited/deleted from the employees page;
- used only as the authorized approver.

### Navigation And Scroll Memory

Implemented soft navigation / PJAX-like behavior for internal transitions.

Also added scroll memory for:

- employees page;
- applications page;
- vacation calendar page.

When returning to a page, the list/calendar should restore the previous scroll position and selected item where applicable.

### Leave Balance Breakdown

Employee profile now shows clearer vacation balance data:

- annual entitlement;
- accrued by tenure;
- requestable limit with advance;
- used;
- reserved;
- factual balance;
- advance available;
- can request.

Important logic:

- unpaid and study leave do not reduce paid leave balance;
- official Russian holidays are excluded from paid leave chargeable days;
- balance supports advance leave after legal eligibility.

## Current Major Change: Annual Vacation Schedule Database

Implemented database foundation for real annual vacation schedules.

Important: **the schedule for 2026 is not created yet**. It must be generated later through future HR functionality.

Created history only for:

`2011-2025`

### New Models In `apps.leave`

Added:

- `VacationSchedule`
- `VacationScheduleItem`
- `VacationScheduleDepartmentApproval`
- `VacationScheduleEnterpriseApproval`
- `VacationScheduleAuthorizedApproval`
- `VacationScheduleChangeRequest`
- `VacationPreference`
- `DepartmentWorkload`
- `DepartmentStaffingRule`

### Meaning Of The New Data

`VacationSchedule`

- one yearly calendar schedule;
- one row per year;
- historical years are created for 2011-2025.

`VacationScheduleItem`

- concrete paid annual leave periods inside a schedule;
- replaces old paid annual vacation requests for history;
- stores risk score, risk level, source, status, transfer links.

`VacationRequest`

Still exists, but its meaning is narrower:

- unpaid leave;
- study leave;
- unplanned / exceptional future cases;
- not the main storage for historical paid annual leave.

`VacationScheduleChangeRequest`

- stores vacation transfer requests;
- includes old/new dates, reason, approver, status, risk analytics.

`VacationPreference`

- stores employee wishes for vacation dates.

`DepartmentWorkload`

- department workload by month.

`DepartmentStaffingRule`

- minimum staff required and maximum allowed absences per department.

## Approval Logic

For annual schedules:

- normal employees are approved by their department head;
- department heads are approved by the enterprise head;
- enterprise head is approved by `admin_1`;
- `admin_1` remains a service account, not a normal employee.

## Demo Database Seeding

The command:

```powershell
.\.venv\Scripts\python.exe manage.py seed_vacation_requests
```

now rebuilds the demo database with:

- 5 departments;
- 100 regular employees;
- 2 HR employees;
- 5 department heads;
- 1 enterprise head;
- 1 service authorized account `admin_1`;
- schedules for 2011-2025;
- no schedule for 2026;
- paid annual leaves in `VacationScheduleItem`;
- unpaid/study requests in `VacationRequest`;
- vacation transfer history;
- department workload history;
- vacation preferences.

Latest local seed check showed:

- departments: 5;
- employees: 109;
- schedules: 15, years 2011-2025;
- schedule 2026: false;
- schedule items: 2172;
- active paid requests: 0;
- change requests: 93;
- department workload rows: 900;
- staffing rules: 5;
- preferences: 1051;
- `admin_1` is clean.

## Balance Logic After Schedule Database

Paid annual schedule items now participate in vacation balance calculations.

Rule:

- past/current approved schedule items count as used;
- future approved/planned schedule items reserve days;
- pending paid vacation requests also reserve days;
- unpaid/study requests do not reduce paid balance.

This allows the future 2026 schedule to reserve employee vacation days after it is generated.

## Tests And Checks

The following checks passed after implementation:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test apps.core apps.leave apps.employees apps.accounts --keepdb
```

Last full test result:

`74 tests OK`

Migration applied locally:

`leave.0004_departmentstaffingrule_departmentworkload_and_more`

## Important Next Steps

1. Connect the existing "График отпусков" page to `VacationScheduleItem`.
2. Keep the current visual calendar UI if possible.
3. Add HR action later: "Сформировать график на 2026 год".
4. Add employee preference collection later: "Опросить сотрудников".
5. Add transfer UI later: employee requests transfer, approver reviews risk and approves/rejects.
6. Add analytics for schedule risks:
   - department workload;
   - minimum staff remaining;
   - overlapping absences;
   - high-risk periods;
   - employees with large remaining balance.

## How To Continue On Another Computer

1. Copy or clone the project folder.
2. Open the project folder in Codex.
3. Open this file: `WORK_SUMMARY.md`.
4. Start a new Codex chat.
5. Paste this file into the new chat and say:

```text
Продолжи работу по этому проекту. Вот summary текущего состояния.
```

6. Then run:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_vacation_requests
```

If `.venv` does not exist on the new computer, create it and install dependencies from `requirements.txt` first.
