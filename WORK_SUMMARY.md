# Work Summary For Continuing Kabinet.pro

Updated: 2026-05-07

## How To Continue In A New Chat

Start by reading:

1. `AGENTS.md`
2. this file
3. `git status --short`

Workspace:

`D:\Fedya\Инст\МАГИСТЕРСКАЯ\Kabinet.pro`

Project name: `Kabinet.pro`.

The UI/domain copy is Russian. On Windows, terminal output can show valid UTF-8
Russian text as mojibake, so verify files with UTF-8 readers or in the browser
before editing Russian copy.

Do not revert unrelated dirty files. The project often has active UI/domain work
in progress between chats.

## Current Product Direction

Kabinet.pro is now a manager cabinet for workforce and vacation planning, not
just a vacation request tracker.

The main product flow is becoming:

- maintain staffing rules and department workload;
- collect employee vacation preferences for the next planning year;
- generate a draft annual vacation schedule;
- explain risks/conflicts through deterministic rules;
- let managers adjust and approve the schedule;
- later add a neural module as decision support, not as decoration.

Do not implement the neural module before the deterministic draft schedule flow
exists. The neural module needs a real planning object to improve and evaluate.

## Recent Committed Work

The login page was fixed and committed separately:

- commit `982fe5f Improve responsive login screen`;
- desktop split login is preserved;
- `<=900px` login uses compact `Сотрудник / Управленец` tabs;
- resizing across the breakpoint now has a soft morph animation.

## Current Large Feature Layer

The current large layer brings the app close to "rules and preferences ready for
draft schedule generation".

Major areas included:

- staffing rules UI and diagnostics;
- department monthly workload editor;
- risk/conflict explanation on calendar, requests and transfers;
- calendar month summary drawer in year mode;
- cell highlighting for risks and conflicts;
- vacation preference collection flow;
- updated request and transfer detail pages;
- application board cards with short risk reasons;
- notification coverage for preference collection and planning tasks;
- shared tooltips and reusable leave-detail panels.

After committing this layer, the next product step should be draft schedule
generation.

## Staffing Rules And Workload

Relevant models include:

- `ProductionGroup`
- `EmployeePosition`
- `DepartmentCoverageRule`
- `ProductionGroupSubstitutionRule`
- `DepartmentWorkload`
- department deputy / enterprise deputy fields

The `/staffing/` page now manages:

- groups;
- positions;
- coverage rules;
- substitution rules;
- department deputy;
- monthly workload for a selected year.

Current access direction:

- HR and enterprise head can edit;
- department head can view own department rules without broad editing;
- demo reset is enterprise-head/debug only.

Department workload is an important input for the future draft generator. It
stores monthly `load_level`, `min_staff_required`, and `max_absent`.

## Risk And Conflict Logic

Risk and conflict are intentionally different:

- conflict means a hard staffing/composition rule is violated;
- high risk means the period is formally possible but should be checked.

Conflict detection considers:

- department minimum staff;
- department maximum absences;
- production group minimum staff;
- production group maximum absences;
- allowed substitutions between production groups;
- substitution capacity and substitute group free reserve;
- department head + deputy simultaneous absence;
- enterprise head + enterprise deputy simultaneous absence.

Important behavior:

- if a group drops below minimum and no substitute can cover it, it is a conflict;
- if substitution covers the shortage, it is high risk, not conflict;
- if the group absence limit is exceeded, it is a conflict;
- duplicate group minimum/limit explanations are combined into one readable card.

Risk explanation is now reused across:

- calendar employee drawer;
- request preview and detail;
- transfer preview and detail;
- applications board cards.

The recommendation panel on request/transfer detail is still deterministic
decision support. It is not the future neural recommendation module.

## Calendar State

The vacation calendar has:

- month/year modes;
- department and production group filters;
- issue filter: `Все / Риски / Конфликты`;
- search;
- risk/conflict highlighting in year month cells and month day cells;
- issue markers in totals and date headers;
- employee drawer with "context + year" layout;
- grouped staffing problems instead of repeated daily technical strings;
- year-mode month summary drawer opened from month totals.

Year-mode month summary shows:

- month metrics;
- days with absent counts and issue markers;
- grouped problem periods;
- absent employees grouped by department/group;
- action to open the month in the calendar.

## Vacation Preferences

New planning-preference entities:

- `VacationPreferenceCollection`
- `VacationPreference`

Routes:

- `/calendar/preferences/start/`
- `/calendar/preferences/<year>/finish/`
- `/preferences/<year>/`

Employees can submit:

- primary preferred vacation period;
- backup period;
- or "no preferences".

HR/enterprise planning users can start and finish a collection. Demo autofill
exists for dissertation/demo data, but the flow is a real model-backed feature.

This is the key input for the next draft schedule generator.

## Requests And Transfers

Request and transfer details now share a more modern decision context:

- employee card;
- summary metrics;
- route/history panels;
- balance and chargeable-day explanation;
- saved-vs-live risk snapshot;
- full risk/context block with tooltips;
- system recommendation panel based on deterministic risk explanation.

Transfer detail now has its own page:

- `/applications/transfers/<id>/`

Schedule transfer preview and creation use the same risk layer as requests.

## Notifications

Notifications cover:

- vacation request approvals;
- schedule transfer approvals;
- manager schedule changes;
- upcoming vacation reminders;
- vacation preference collection tasks.

Useful commands:

```powershell
.\.venv\Scripts\python.exe manage.py backfill_notifications
.\.venv\Scripts\python.exe manage.py send_upcoming_vacation_reminders --days-before 7
```

## Demo Data

The seed command now creates:

- departments and role users;
- realistic production groups;
- positions;
- coverage and substitution rules;
- department workload;
- deputies;
- preference collections/preferences;
- schedule items and requests with softened risk distribution.

Run:

```powershell
.\.venv\Scripts\python.exe manage.py seed_vacation_requests --confirm-reset
```

Demo password remains `1234`.

## Tests Last Run

Last successful checks on 2026-05-07:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test apps.accounts apps.employees apps.leave apps.core --keepdb
```

The full run found 307 tests and passed.

Note: one earlier `--keepdb` full run hit a transient PostgreSQL deadlock during
a migration test and two stale-state failures, but rerunning the affected tests
and then the full suite passed. If this appears again, rerun once or run without
`--keepdb` to rebuild the test schema.

## Current Housekeeping

Temporary browser screenshots and `vacation-detail-dom-check.json` were removed
from the repository root before committing the large feature layer.

If new Playwright screenshots are needed, keep them local and do not commit them
unless the user explicitly asks for visual artifacts.

## Next Recommended Product Step

Build **Draft Schedule Generator V1** before the neural module.

Suggested scope:

1. Add a service that creates a draft `VacationSchedule` for a target year from:
   - employee preferences;
   - available paid balance;
   - department workload;
   - staffing and substitution rules;
   - existing schedule/request conflicts.
2. Generate schedule items in `draft` or `planned` state with source metadata.
3. Score each generated item with the existing risk layer.
4. Show generation results in the calendar:
   - preferences satisfied;
   - skipped/no preference employees;
   - conflicts;
   - high-risk months/groups;
   - employees needing manual placement.
5. Allow managers to adjust draft items manually.
6. Only after that, implement the neural module as:
   - model-backed recommendation scoring;
   - stored recommendation runs;
   - comparison between deterministic draft and neural suggestions.

This is the clearest next step because the system already has the required
inputs and explanations; it now needs to produce an actual yearly draft.

## Important Commands

Run checks:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test apps.accounts apps.employees apps.leave apps.core --keepdb
```

Run local server:

```powershell
.\scripts\django_server.ps1 -Action restart -Port 8001 -ReadyTimeoutSeconds 10
.\scripts\django_server.ps1 -Action status -Port 8001
.\scripts\django_server.ps1 -Action stop -Port 8001
```
