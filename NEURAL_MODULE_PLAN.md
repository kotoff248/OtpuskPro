# Neural Module Plan For Kabinet.pro

Updated: 2026-04-28

This file captures the minimum acceptable direction for the neural network module
so future work does not degrade into a decorative "AI" label.

## Reference Level

Local reference project:

`D:\Fedya\Инст\МАГИСТЕРСКАЯ\air_monitor_back-main`

The reference project has one real PyTorch neural network, but it is surrounded
by a full research pipeline:

- dataset snapshot;
- model version;
- training configuration;
- stored checkpoint;
- metrics and training history;
- prediction/recommendation run;
- evaluation/backtest;
- experiment run/series;
- API/admin access to inspect the results.

Kabinet.pro does not need to copy its air-quality model. It should copy only the
engineering standard: the neural module must be traceable, reproducible and
explainable enough for a dissertation.

## What We Must Not Do

Do not implement the neural module as:

- a random number generator with an "AI" label;
- a simple hand-written risk formula pretending to be a neural network;
- a single `predict()` helper with no stored dataset, version, metrics or result;
- copied names or architecture from the air-monitoring project;
- UI text that says "ИИ" without a backend model and saved outputs.

That would be below the required quality bar.

## Target Module

Build a neural decision-support module for annual vacation schedule planning.

Working name:

`Neural vacation planning and risk scoring module`

Purpose:

- recommend candidate vacation periods for the next yearly schedule;
- estimate risk for each candidate period;
- help a manager compare schedule variants;
- explain why a recommendation is good or risky.

The model should support, not replace, the manager. Final schedule approval must
remain a human workflow.

## How It Should Differ From The Reference Project

The reference project predicts air quality time series with a GRU model.

Kabinet.pro should solve a different task:

- domain: employees, departments, vacation schedules and workload;
- input: employee, department, month, balance, workload, preferences, overlaps;
- output: risk score / recommendation priority for vacation planning;
- UI result: recommended vacation periods and explanations for the manager.

A compact PyTorch MLP for tabular HR/planning features is the preferred first
model. A GRU can be considered later only if we intentionally model monthly or
historical sequences.

## Minimum Database Entities

Implement equivalents of the reference pipeline with project-specific names:

- `LeaveDatasetSnapshot` - fixed training dataset, feature list, target list and metadata;
- `LeaveModelVersion` - trained model status, metrics, history, checkpoint and active flag;
- `ScheduleRecommendationRun` - one recommendation generation run for a target year;
- `ScheduleRecommendationItem` - recommended employee period with risk, confidence and explanation;
- `ScheduleRecommendationEvaluation` - quality/backtest metrics for recommendations.

Optional later:

- `LeaveExperimentRun`;
- `LeaveExperimentSeries`;
- scheduled/background training tasks.

## First Dataset

Build training rows from existing structured data:

- `Employees`;
- `Departments`;
- `VacationSchedule`;
- `VacationScheduleItem`;
- `VacationRequest`;
- `VacationScheduleChangeRequest`;
- `VacationPreference`;
- `DepartmentWorkload`;
- `DepartmentStaffingRule`;
- leave balance/ledger services.

Example candidate row:

```text
employee_id=17
department_id=3
role=employee
tenure_months=28
month=7
requested_days=14
available_balance=31
department_load_level=5
min_staff_required=4
max_absent=2
overlap_count=2
remaining_staff=3
matches_primary_preference=1
holiday_days_inside=0
historical_rejection_rate=0.18
target_risk=high
```

## First Model

Preferred MVP model:

`VacationRiskNet`

Type:

- PyTorch;
- tabular MLP;
- input: normalized numeric/categorical planning features;
- output: risk score or probability of acceptable recommendation.

Example output:

```json
{
  "risk_score": 72,
  "risk_level": "high",
  "confidence": 0.81,
  "recommendation": "avoid",
  "explanation": [
    "В июле высокая нагрузка отдела",
    "Одновременно отсутствуют 2 сотрудника",
    "Останется меньше минимального состава"
  ]
}
```

The explanation can be rule-assisted at first. The neural model provides the
score; the service explains the score using the strongest input factors.

## MVP Implementation Steps

1. Add database entities and migrations for dataset/model/recommendation runs.
2. Add `apps.leave.ml.dataset` to build reproducible training payloads.
3. Add `apps.leave.ml.training` with `VacationRiskNet`.
4. Add `apps.leave.ml.inference` to load the active model and score candidate periods.
5. Add `apps.leave.services.ai_planning` to generate recommendation runs for a target year.
6. Add a manager-facing planning UI section that shows recommendations before creating schedule items.
7. Add tests for dataset validation, model training, inference shape, saved recommendations and fallback behavior.

## Dissertation Angle

Describe the module as:

`нейросетевой модуль поддержки принятия решений при формировании графика отпусков`

It should be presented as part of an information-analytical leadership cabinet:

- it analyzes historical schedules and department workload;
- it estimates planning risk;
- it recommends schedule options;
- it stores model versions and metrics;
- it keeps human approval as the final decision point.

