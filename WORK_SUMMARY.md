# Work Summary For Continuing In Codex

Updated: 2026-04-26

## Project

This is a Django 5 web application for employee vacation management. The current local workspace is:

`D:\Инст\Диссертация\Website`

The system covers:

- employee and management login;
- personal cabinet and employee profile pages;
- employee and department directories;
- month/year vacation calendar;
- vacation requests and schedule transfer requests;
- role-based approvals;
- basic analytics.

Domain assumption: Far North / Norilsk-style vacation rules. The default annual paid leave norm is 52 calendar days: 28 basic days plus 24 additional Far North days.

## Running On A New Computer

Use Python with a virtual environment and PostgreSQL.

1. Create `.env` from `.env.example`.
2. Fill PostgreSQL connection variables:
   - `DB_NAME`
   - `DB_USER`
   - `DB_PASSWORD`
   - `DB_HOST`
   - `DB_PORT`
3. Install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

4. Apply migrations:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

5. Rebuild demo data:

```powershell
.\.venv\Scripts\python.exe manage.py seed_vacation_requests
```

6. Run the server:

```powershell
.\.venv\Scripts\python.exe manage.py runserver
```

There is also a helper script:

```powershell
.\run_postgres.ps1
```

The login page is `/`, not `/login/`.

## Demo Data And Accounts

The seed command deletes and recreates demo enterprise data. Default password for generated users is:

`1234`

Generated login patterns:

- `director_1` - enterprise head;
- `admin_1` - authorized service approver for enterprise-head requests;
- `hr_1`, `hr_2` - HR users;
- `manager_1` ... `manager_5` - department heads;
- `employ_1` ... `employ_100` - regular employees.

The seed creates 5 departments, department heads, 2 HR employees, 1 enterprise head, 100 regular employees, staffing rules, monthly workload, vacation schedules, requests, transfer history, preferences and leave ledger allocations.

Useful seed options:

```powershell
.\.venv\Scripts\python.exe manage.py seed_vacation_requests --seed-value 42
.\.venv\Scripts\python.exe manage.py seed_vacation_requests --fast
```

## Apps And Routes

Main apps:

- `apps.accounts` - login/logout, role helpers, `User` sync;
- `apps.employees` - employees, departments, profile pages and employee forms;
- `apps.leave` - calendar, vacation requests, schedule transfer requests, approvals, analytics;
- `apps.core` - demo data command and shared project helpers.

Important routes:

- `/` - login;
- `/main/` - current user's profile cabinet;
- `/employees/` - employee list;
- `/employee/<id>/` - employee profile;
- `/departments/` - department list;
- `/calendar/` - vacation calendar;
- `/applications/` - request approval page;
- `/applications/<id>/` - vacation request detail;
- `/analytics/` - analytics dashboard.

Settings module is `config.settings.postgres`. Base settings read `.env` automatically. When `DJANGO_DEBUG=false`, the project requires a strong `DJANGO_SECRET_KEY` and configured `DJANGO_ALLOWED_HOSTS`.

## Roles And Access

Employee roles live in `apps.employees.models.Employees`:

- `employee`;
- `hr`;
- `department_head`;
- `enterprise_head`;
- `authorized_person`.

Access and approval rules are centralized mostly in `apps.accounts.services`.

Current behavior:

- regular employees use the employee side of login;
- HR, department heads, enterprise head and authorized person use management login;
- authorized person is a service role and redirects to applications after login;
- HR can edit employee data and create departments;
- department head sees their department scope;
- enterprise head sees broad management scope;
- authorized person approves only enterprise-head requests.

Vacation request approval:

- regular employee request -> department head;
- HR or department head request -> enterprise head;
- enterprise head request -> authorized person `admin_1`;
- users cannot approve their own requests.

## Vacation Domain Model

Paid annual leave is primarily represented in yearly schedules:

- `VacationSchedule` - yearly schedule;
- `VacationScheduleItem` - concrete paid annual leave period in the schedule;
- `VacationRequest` - unpaid leave, study leave, paid request from free balance, and rare paid exceptions outside schedule;
- `VacationScheduleChangeRequest` - request to transfer an existing schedule item.

The current year is the end year for seeded schedules. Seed history defaults to 5 full years before the current year. For 2026 this means schedules for 2021-2026.

Calendar day cost:

- paid leave excludes Russian public holidays from chargeable days;
- unpaid and study leave do not reduce paid leave balance.

Status "Работает / В отпуске" is not stored as a manual employee flag. It is calculated from active approved vacation requests and active schedule items.

## Leave Ledger

The old simple balance fields were removed from active use:

- `is_working`;
- `vacation_days`;
- `used_up_days`;
- legacy employee `password`.

Passwords live in Django `User`. Employee records link to `User` via `Employees.user`.

The current leave balance system is ledger-based:

- `VacationEntitlementPeriod` - employee working year and leave entitlement;
- `VacationEntitlementAllocation` - allocation of paid days from working years to a request or schedule item.

Rules:

- paid days are allocated from the oldest available working year first;
- future working years cannot be used;
- rejected, cancelled and transferred sources do not reserve or use paid balance;
- invalid paid leave raises validation errors instead of silently corrupting balance.

Profiles and request details show working-year balances and leave summaries.

## Schedule Transfers

Employees can request a transfer for future active schedule items from the calendar detail drawer.

Flow:

1. Employee opens a future scheduled vacation in `/calendar/`.
2. Clicks "Запросить перенос".
3. Chooses new dates and enters reason.
4. System calculates risk, workload, overlaps, remaining staff, minimum staff and balance after change.
5. Original schedule item remains active while the transfer request is `pending`.
6. Approver reviews the request in `/applications/`.
7. On approval, the old schedule item becomes `transferred`, a new schedule item is created with `source=transfer`, and it links back to the original item and change request.
8. On rejection, the original schedule item stays unchanged.

Applications page shows transfer requests above regular vacation requests. Pending navigation counter includes both pending regular requests and pending transfer requests.

## Current UI State

The main UI uses shared dark panels, cyan accents, compact cards and sectioned profile pages.

Current pages:

- login `/`;
- profile `/main/`;
- employee profile `/employee/<id>/`;
- employees `/employees/`;
- departments `/departments/`;
- calendar `/calendar/`;
- applications `/applications/`;
- vacation detail `/applications/<id>/`;
- analytics `/analytics/`.

Recent visual work:

- global visual radius system moved into the main CSS files;
- old profile-only radius scope was removed;
- large panels, nested cards, badges, statuses, buttons, selects and modals now use shared radius tokens;
- segmented controls now calculate the inner thumb radius from the parent plaque radius and padding;
- active segmented text moves together with the thumb on hover;
- this applies to calendar "Месяц / Год", employee status filter, and applications status filters;
- calendar month/year tiles, employee cards, day cells and year-month tracks were aligned with the radius system;
- employee cards, department cards, application cards, transfer action buttons and detail action buttons were aligned;
- login inputs, buttons, auth kicker and moving toggle panel use the same radius language, but the moving auth panel has its own stronger radius tokens;
- login card colors were restored to the earlier look; only the hover lift remains;
- login base shadow is intentionally calmer than hover shadow, so hover now feels like the main site's card lift.

Important frontend files:

- `static/css/main.css` - global layout, sidebar, profile pages, shared radius tokens;
- `static/css/calendar.css` - calendar board, month/year view, custom selects, calendar modals;
- `static/css/employees.css` - employees/departments/profile management surfaces;
- `static/css/applications.css` - applications board, transfer cards, status segmented controls;
- `static/css/login_style.css` - standalone login page styling;
- `static/js/base.js` - sidebar, PJAX-like container replacement, modals;
- `static/js/calendar.js` - calendar filtering, custom selects, modals, detail drawer;
- `static/js/employees-page.js` - employee status filtering and card rendering;
- `static/js/applications-page.js` - applications filters, AJAX rendering, transfer actions;
- `static/js/profile-sections.js` - sectioned pages and scroll memory.

## Current Technical Notes

- Templates are in `templates/`; shared pieces are in `templates/includes/`.
- `templates/base.html` is used by internal authenticated pages.
- `templates/login.html` is standalone and uses only `login_style.css` plus `static/js/script.js`.
- Calendar adds `is-calendar-page` classes to `html` and `body` for sizing.
- `base.js` updates `body` classes when replacing the app container, which prevents calendar body classes from leaking after navigation.
- Employee links in JS use backend-provided `profile_url`, not hardcoded `/employee/` concatenation.
- Applications filters preserve department and status across transfer/request sections.
- Custom selects are implemented for calendar filters and employee/department filters.

## Useful Commands

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_vacation_requests
.\.venv\Scripts\python.exe manage.py test apps.accounts apps.employees apps.leave apps.core --keepdb
```

If the test database schema is stale, run tests once without `--keepdb`.

Quick route smoke test can be done with Django test client after setting:

`DJANGO_SETTINGS_MODULE=config.settings.postgres`

## Last Verified

Recently verified:

- `.\.venv\Scripts\python.exe manage.py check` passes;
- CSS brace counts were checked for recently edited CSS files;
- login route `/` returns 200 in a temporary local Django smoke test;
- authenticated routes redirect to login when unauthenticated, which is expected.

Visual browser verification was limited by the local Codex environment: starting a long-running server through PowerShell/Start-Process was unreliable here. The code itself runs through Django checks.

## Next Major Work

Recommended next work:

1. Build HR workflow for generating and editing a new yearly schedule.
2. Add notification system for approvals, rejected requests and transfer decisions.
3. Add employee preference collection campaign for future schedules.
4. Expand analytics for schedule risks, old balances, department load and overlap hotspots.
5. Add export/reporting for schedules, requests and leave ledger.
6. Add ML/risk-scoring layer only after enough structured history and acceptance rules are stable.

## Transfer Checklist

Before moving to another computer:

- copy the project directory;
- do not rely on the old virtual environment if Python paths differ; recreate `.venv`;
- copy `.env` only if it is safe to move local DB credentials;
- install PostgreSQL and create the target database/user;
- run migrations;
- run seed if a fresh demo database is acceptable;
- run `manage.py check`;
- open `/` and log in with a seeded account.
