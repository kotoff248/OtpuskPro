# Neural Module Plan For Kabinet.pro

Updated: 2026-05-14

This file fixes the current architecture direction for the neural module in
Kabinet.pro. The module must grow out of the real vacation schedule draft
generator, not sit next to it as a decorative "AI" feature.

## Short Thesis Formulation

`нейросетевой модуль поддержки принятия решений при формировании графика отпусков`

The module helps HR and managers choose the best vacation periods while keeping
hard legal/business rules deterministic and keeping the final approval human.

## Old Logic

The previous plan described a separate recommendation pipeline:

- create separate dataset/model/recommendation entities;
- generate recommendations before creating schedule items;
- show recommended periods in a separate manager-facing planning section;
- later create schedule items from those recommendations;
- train a compact PyTorch MLP on historical HR/planning data;
- store model versions, metrics, recommendation runs and evaluations.

That direction was correct as a quality bar, but it was too detached from the
actual system flow. It risked duplicating the draft generator and making the
neural module look like a parallel feature instead of part of schedule creation.

## Current Logic

The neural module is now designed as a candidate scorer/corrector inside the
existing draft vacation schedule workflow.

The current draft generator remains the base:

- it collects primary and backup vacation preferences;
- it calculates available paid leave and mandatory leftovers;
- it creates multiple candidate periods for each employee;
- it checks legal/business hard rules;
- it evaluates staffing conflicts and department risk;
- it creates draft `VacationScheduleItem` records only from candidates that pass
  hard rules.

The neural module will be added after this deterministic layer:

1. The system creates several candidates for an employee.
2. Hard rules reject impossible candidates first.
3. Each candidate is saved with features.
4. The neural module scores only candidates that can legally be considered.
5. Hybrid logic chooses the best candidate using rules plus neural score.
6. The selected candidate is linked to the created schedule item.
7. The UI shows why the period was chosen and what risks were detected.
8. HR and managers can leave feedback on the selected candidate.

This means the neural module does not replace the generator. It improves the
choice between valid alternatives.

## Implemented Foundation

The codebase already has the foundation for the module:

- `DraftGenerationCandidate` in `apps.leave.services.schedule_drafts`;
- `VacationScheduleGenerationRun` for a saved generation attempt;
- `VacationScheduleCandidate` for every considered period;
- links from `VacationScheduleItem` to `generation_run` and `selected_candidate`;
- `VacationScheduleCandidateFeedback` for HR/manager feedback on selected draft
  candidates;
- hard-rule metadata:
  - `passed_hard_rules`;
  - `block_reason_key`;
  - `block_reason`;
  - risk score and risk level;
- feature schema version `1` in candidate `features`;
- feature groups:
  - `employee_*`;
  - `period_*`;
  - `planning_*`;
  - `preference_*`;
  - `risk_*`.

The current generation mode is `hybrid`. The default scorer can fall back to
`vacation-candidate-mlp-v1`, but the dissertation demo should use the trained
`vacation-candidate-mlp-v2` artifact through:

```env
VACATION_CANDIDATE_SCORER_VERSION=vacation-candidate-mlp-v2
```

Candidate records receive score, confidence, recommendation and explanation,
and selected schedule items store the selected candidate score in their AI
fields. HR and managers can mark a selected candidate as accepted, needing
correction, or rejected; that feedback is stored with score, confidence, model
version and explanation snapshots.

## Target Behavior

When HR clicks to generate or complete the draft:

- the system creates a generation run;
- each employee receives candidate periods;
- blocked candidates are stored with a reason;
- valid candidates are stored with features and risk data;
- the active MLP scorer ranks suitable candidates by model score;
- the chosen candidate is saved on the resulting schedule item.
- HR and managers leave feedback on the selected candidate before the final
  approval path.

For the dissertation, this gives a traceable chain:

`employee data -> candidate periods -> hard-rule filtering -> features -> model score -> selected schedule item -> human feedback -> manager approval`

## Hard Rules Stay Deterministic

The neural module must never override hard rules.

Hard rules include:

- invalid or empty period;
- paid leave not available yet;
- no chargeable paid leave days;
- period longer than the remaining amount being distributed;
- overlap with active vacation requests;
- overlap with existing schedule items;
- staffing conflict that violates department composition rules;
- negative paid leave balance.

If a candidate fails these rules, it can be stored and explained, but it cannot
be selected by the neural module.

## Candidate Features

Candidate features must stay stable and machine-readable.

Current feature groups:

- employee features:
  - role;
  - management flag;
  - department and production group identifiers;
  - annual paid leave norm;
  - manual balance adjustment;
  - tenure at year end;
- period features:
  - start/end month;
  - day of year;
  - calendar days;
  - chargeable days;
  - summer overlap;
  - cross-month flag;
- planning features:
  - available days;
  - target days;
  - already placed days;
  - open required days;
  - mandatory/blocking days;
  - nearest deadline gap;
  - candidate coverage ratio;
  - remainder policy;
- preference features:
  - whether a preference exists;
  - primary/backup priority;
  - exact preference match;
  - preference period length;
- risk features:
  - risk score;
  - risk level;
  - conflict flag;
  - department load;
  - overlapping absences;
  - remaining staff;
  - minimum required staff;
  - staff margin;
  - substitution flag;
  - primary risk detail.

These features are the first training/inference contract for the neural module.

## Active Neural Scoring

The first neural model is a compact tabular MLP.

Implemented models:

- `vacation-candidate-mlp-v1`: bundled safe JSON MLP artifact;
- `vacation-candidate-mlp-v2`: trained on historical candidates, feedback and
  packages created by the seed command.

Type:

- pure Python feed-forward inference with a JSON weight artifact;
- tabular MLP;
- input: normalized candidate features from schema version `1`;
- output:
  - candidate score from 0 to 100;
  - confidence from 0 to 100;
  - recommendation class such as `prefer`, `normal`, `avoid`.

The model should score candidate periods, not invent periods from scratch. The
period search remains the responsibility of the deterministic generator.

Runtime files:

- model inference: `apps.leave.services.candidate_neural`;
- model artifacts:
  - `apps/leave/ml_models/vacation_candidate_mlp_v1.json`;
  - `apps/leave/ml_models/vacation_candidate_mlp_v2.json`;
  - `apps/leave/ml_models/vacation_candidate_mlp_v2_metrics.json`;
- scoring facade/fallback: `apps.leave.services.candidate_scoring`.

Training command:

```powershell
.\.venv\Scripts\python.exe manage.py train_vacation_candidate_model
```

PyTorch is used only during training. Normal page rendering and runtime scoring
must not import PyTorch.

## Hybrid Selection Logic

The intended selection order:

1. Generate candidates.
2. Save every candidate.
3. Block candidates that fail hard rules.
4. Score candidates that passed hard rules.
5. Sort candidates by:
   - neural score;
   - lower risk;
   - stronger preference match;
   - better coverage of open required days;
   - earlier mandatory deadline closure when applicable.
6. Select the top candidate, with a business-priority correction: if the primary
   employee preference is safe, not high-risk, not marked `avoid`, and close in
   score to the backup preference, choose the primary preference because it is
   the employee's first choice.
7. Save selected candidate metadata on `VacationScheduleItem`.

Fallback:

- if model inference fails, use `candidate-scorer-baseline-v1` as a safe
  fallback and mark the model version as fallback;
- never create an invalid schedule item only because the model score is high.

The same scorer is now also used for urgent previous-year closure options:
the system builds valid periods before the deadline, checks overlaps/staffing
risks, scores the options, and shows the module score in the urgent-closure
modal. Seed no longer creates active urgent-closure approvals in advance; HR
starts that flow manually from the draft.

## User-Facing Explanation

The interface should eventually show:

- selected period;
- whether it was selected by rules or hybrid neural mode;
- model score and confidence;
- strongest positive factors;
- strongest risk factors;
- hard-rule block reasons for rejected alternatives when useful.
- human feedback from HR and managers.

The explanation can be rule-assisted. The neural model gives a score, while the
service explains it through the strongest saved feature values and risk details.

## Official Roadmap Status

Use this numbered roadmap when discussing stages with the user. Some technical
substeps were implemented separately, but they map to these product stages.

Completed:

1. Add models and migrations for generation runs and candidates.
2. Implement full multi-candidate generation for the draft.
3. Connect hard candidate validation as a separate layer.
4. Add baseline scoring without a neural network.
5. Fully move initial draft creation to candidates and scoring.
6. Move `Добрать незакрытые дни` to the same candidate/scoring mechanism.
7. Show scores and explanations in the draft UI.
8. Add feedback from HR and department heads.
9. Connect the real neural module instead of baseline scoring.
10. Verify the full scenario and prepare the demonstration result.
11. Train and connect v2 scorer from historical seed traces.
12. Calibrate v2 scores so normal selected vacations no longer collapse to
    near-zero or identical `68%` values.
13. Use the same hard-rule + neural scoring approach for urgent previous-year
    closure options.

Remaining:

- None in the neural-module roadmap. The next large product step is schedule
  approval after HR finishes the draft.

## Dissertation Angle

In the dissertation, the module should be described as part of an
information-analytical manager cabinet:

- it uses employee, department, workload, preference and risk data;
- it forms multiple vacation-period candidates;
- it filters candidates by deterministic hard rules;
- it extracts structured features for analysis;
- it applies neural scoring to compare valid alternatives;
- it stores generation runs and decisions for auditability;
- it collects HR/manager feedback as a future training and evaluation signal;
- it keeps HR and manager approval as the final decision.

The important claim is not "the system has AI". The important claim is:

`the system contains a traceable neural decision-support module embedded into the formation of the vacation schedule draft`.

## Current Product Direction After The Neural Roadmap

The neural module itself is no longer the main blocker. The next system-level
work is the approval process that consumes the neural draft:

1. HR completes the draft until manual tasks, hard conflicts and blocking urgent
   leftovers are resolved.
2. HR sends the draft to department heads.
3. Each department head reviews only their department, using the saved module
   scores, risks and explanations as decision support.
4. Department heads either approve their department or return it to HR with a
   comment.
5. After all departments approve, the enterprise head reviews the full schedule.
6. Final approval moves the schedule from draft/review state to an active
   approved schedule.

This approval flow should not retrain or bypass the neural module. It should
preserve the candidate audit trail and use feedback as a future training signal.
