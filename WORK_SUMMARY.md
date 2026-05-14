# Kabinet.pro - Handoff Summary

Updated: 2026-05-14

Этот файл нужен для продолжения работы в другом чате или на другом компьютере.
Сначала читать:

1. `AGENTS.md`
2. `WORK_SUMMARY.md`
3. `NEURAL_MODULE_PLAN.md`
4. `git status --short`

Рабочая папка на текущем компьютере:

`D:\Fedya\Инст\МАГИСТЕРСКАЯ\Kabinet.pro`

Проект называется `Kabinet.pro`. Не использовать старое название `OtpuskPro` в
новых текстах, UI и описаниях.

## Главное Сейчас

Система готовится к демонстрации создания графика отпусков на 2027 год.
Основной сценарий:

1. HR запускает сбор пожеланий.
2. Демо-сотрудники заполняют пожелания.
3. HR создает черновик графика.
4. HR нажимает `Добрать незакрытые дни`.
5. Нейромодуль выбирает лучшие допустимые периоды через hard rules + v2-score.
6. HR вручную разбирает срочные остатки и конфликтные случаи.
7. Дальше нужно переходить к полноценному согласованию графика.

Единое название действия в UI:

`Добрать незакрытые дни`

Не возвращать в интерфейс варианты `Автоматически распределить`,
`нераспределенные дни`, `оставшиеся дни` как название кнопки.

## Что Уже Сделано

### Исторические ML-следы в seed

`seed_vacation_requests --confirm-reset` создает исторические:

- `VacationScheduleGenerationRun`;
- `VacationScheduleCandidate`;
- `VacationScheduleCandidatePackage`;
- `VacationScheduleCandidatePackagePeriod`;
- `VacationScheduleCandidateFeedback`;
- выбранные, отклоненные и заблокированные candidates;
- связи schedule items с selected candidate и AI-полями.

История используется как база для обучения, но будущий draft 2027 не считается
историей.

### v2-нейромодуль

Обучение делается через PyTorch, но обычный сайт PyTorch не импортирует.
Runtime-скоринг работает через JSON-веса и pure Python inference.

Команда обучения:

```powershell
.\.venv\Scripts\python.exe manage.py train_vacation_candidate_model
```

Файлы модели:

- `apps/leave/ml_models/vacation_candidate_mlp_v2.json`
- `apps/leave/ml_models/vacation_candidate_mlp_v2_metrics.json`

Активная версия задается в `.env`:

```env
VACATION_CANDIDATE_SCORER_VERSION=vacation-candidate-mlp-v2
```

Если v2 не найдена или JSON сломан, система безопасно падает на v1/baseline.

### Калибровка оценок

Убрана искусственная подпорка, из-за которой почти все варианты получали около
`68%`. Теперь оценка зависит от:

- совпадения с основным/запасным пожеланием;
- длины периода;
- риска;
- нагрузки отдела;
- запаса состава;
- закрытия срочного остатка;
- того, что часть отпуска может добраться позже.

Ожидаемая шкала:

- хороший primary: примерно `78-90%`;
- нормальный partial primary: примерно `68-82%`;
- хороший backup: примерно `62-78%`;
- допустимый, но рискованный период: примерно `45-65%`;
- blocked: `0%`.

### Оптимальный добор дней

`Добрать незакрытые дни` работает в фоне через `VacationScheduleAutoPlaceJob`.
Кнопка не должна зависать в браузере.

Фоновая команда:

```powershell
.\.venv\Scripts\python.exe manage.py run_schedule_draft_auto_place --job-id <id> --year 2027 --actor-id <hr_id>
```

Автодобор использует умный подбор пакетов:

`auto_place_remaining_schedule_draft(..., use_package_selection=True)`

Он сравнивает допустимые варианты и может выбирать 1/2/3 периода, а не просто
ставить всем одинаковую схему.

### Прогресс фоновых задач

Сделано:

- полный reset демо-БД идет в фоне через `DemoDataResetJob`;
- модалка reset показывает процент и текущий этап;
- повторный клик не запускает второй seed, а возвращает активную задачу;
- `Добрать незакрытые дни` показывает прогресс в модалке;
- прогресс добора дублируется на странице планирования;
- черновик можно открыть во время фонового добора;
- на странице черновика тоже есть плашка прогресса.

### Быстрый сброс

Есть кнопка `Сбросить до начальных настроек`.

Она:

- не запускает полный seed;
- не разлогинивает пользователя;
- быстро очищает работу по 2027;
- откатывает правила состава/нагрузку к snapshot;
- не трогает исторические графики, исторические ML-следы и JSON-модели.

Доступ в `DEBUG`: директор предприятия и HR.

### Срочное закрытие остатков

Свежая важная правка:

- seed больше не создает заранее активные срочные закрытия;
- быстрый snapshot больше не восстанавливает активные срочные закрытия;
- в черновике должна появляться ручная кнопка `Закрыть в 2026`;
- даты для срочного закрытия теперь тоже ранжируются нейромодулем;
- в модалке срочного закрытия показывается `Оценка модуля`.

Важно: если в уже существующей локальной БД остались старые активные срочные
заявки, код сам их не удаляет. Чтобы увидеть ручную кнопку, нужно выполнить
`Сбросить до начальных настроек` или полный reseed. Перед полным reseed всегда
спросить пользователя.

## Важные Файлы

- `apps/core/management/commands/seed_vacation_requests.py`
- `apps/core/management/commands/train_vacation_candidate_model.py`
- `apps/core/services/demo_baseline.py`
- `apps/core/services/demo_locks.py`
- `apps/core/services/demo_reset_jobs.py`
- `apps/leave/services/historical_ml_traces.py`
- `apps/leave/services/candidate_training.py`
- `apps/leave/services/candidate_neural.py`
- `apps/leave/services/candidate_scoring.py`
- `apps/leave/services/schedule_drafts.py`
- `apps/leave/services/schedule_auto_place_jobs.py`
- `apps/leave/services/urgent_closures.py`
- `apps/leave/management/commands/run_schedule_draft_auto_place.py`
- `templates/vacation_schedule_draft.html`
- `templates/vacation_schedule_planning.html`
- `templates/includes/schedule_draft_urgent_closure_modal_body.html`
- `static/js/schedule-draft.js`
- `static/js/schedule-planning.js`
- `static/css/pages/schedule-draft.css`
- `static/css/pages/schedule-planning.css`

## Миграции, Которые Нужны На Другом Компьютере

Просто выполнить:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

Недавние миграции:

- `apps/core/migrations/0004_demobaselinesnapshot.py`
- `apps/core/migrations/0005_demodataresetjob.py`
- `apps/leave/migrations/0021_vacationscheduleautoplacejob.py`

## Перенос На Другой Компьютер

1. Скопировать проект.
2. Создать/проверить `.env` по `.env.example`.
3. Установить зависимости:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Если зависает PyTorch, не ждать молча: установить PyTorch вручную и продолжить.

4. Применить миграции:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

5. Проверить активную модель:

```env
VACATION_CANDIDATE_SCORER_VERSION=vacation-candidate-mlp-v2
```

6. Если БД не переносится, создать демо-данные:

```powershell
.\.venv\Scripts\python.exe manage.py seed_vacation_requests --confirm-reset --seed-value 42
```

Перед reseed существующей демо-БД спросить пользователя.

7. Если v2 JSON не скопирован, обучить:

```powershell
.\.venv\Scripts\python.exe manage.py train_vacation_candidate_model
```

8. Запустить сервер:

```powershell
.\scripts\django_server.ps1 -Action restart -Port 8001 -ReadyTimeoutSeconds 10
```

9. Открыть и проверить:

- `/staffing/`
- `/calendar/planning/2027/`
- `/calendar/planning/2027/?stage=draft`
- `/calendar/drafts/2027/`

## Последние Проверки

После последних правок успешно проходили:

```powershell
node --check static/js/schedule-draft.js
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test apps.leave.tests.test_urgent_closures --keepdb
.\.venv\Scripts\python.exe manage.py test apps.core.tests.test_seed_vacation_data.SeedVacationDataCommandTests.test_command_generates_non_overlapping_active_vacations_and_metrics --keepdb
```

Ранее также проходили тесты по staffing, preferences и auto-place.

## Текущее Dirty-Состояние

Рабочее дерево специально грязное. Это накопленные изменения текущих этапов,
их не откатывать без прямой просьбы пользователя.

Основные измененные зоны:

- demo reset/progress;
- planning progress;
- draft progress;
- auto-place jobs;
- urgent closures;
- seed historical ML traces / baseline snapshot;
- tests for seed, staffing, preferences, auto-place and urgent closures.

## Что Делать Дальше

Ближайший разумный путь:

1. На новом компьютере поднять проект и проверить миграции/сервер.
2. Убедиться, что v2-модель активна.
3. Проверить визуально:
   - HR видит reset/restore;
   - `Добрать незакрытые дни` работает в фоне;
   - прогресс виден на planning и draft;
   - черновик открывается во время добора;
   - срочное закрытие показывает кнопку `Закрыть в 2026`;
   - в срочном закрытии есть оценки модуля.
4. После этого переходить к следующему большому этапу:
   полноценное согласование графика 2027.

Следующий большой этап:

- HR отправляет черновик руководителям отделов;
- руководители отделов согласуют или возвращают свои отделы;
- HR исправляет возвращенные отделы;
- директор предприятия согласует весь график;
- уполномоченное лицо финализирует, если требуется;
- draft становится утвержденным графиком.

## Правила Для Следующего Чата

- Не делать полный reseed без вопроса пользователю.
- Если надо работать с demo-БД, спрашивать: пересоздавать/сбрасывать или нет.
- Не запускать долгий `pip install` молча.
- Не ослаблять hard rules ради красивой оценки модели.
- Нейромодуль выбирает только среди допустимых вариантов.
- Русский UI проверять как UTF-8, не чинить “кракозябры” только по выводу PowerShell.
- Не коммитить и не stage-ить без просьбы пользователя.
