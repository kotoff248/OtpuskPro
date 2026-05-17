# Kabinet.pro

Веб-приложение на Django для управления отпусками, графиком отпусков,
согласованиями и кадровым планированием.

## Структура проекта

- `manage.py` — точка входа Django.
- `config/` — маршруты проекта, `ASGI/WSGI` и настройки.
- `config/settings/base.py` — общие настройки проекта.
- `config/settings/postgres.py` — конфигурация PostgreSQL.
- `apps/accounts/` — вход в систему и привязка сотрудников к `django.contrib.auth`.
- `apps/core/` — общие сигналы, уведомления, management-команды и demo/reset
  сервисы.
- `apps/core/services/demo_seed/` — внутренняя логика создания demo-данных.
- `apps/employees/` — сотрудники, отделы, формы и профили.
- `apps/leave/` — заявки на отпуск, календарь, согласование и аналитика.
- `apps/leave/views/` и `apps/leave/urls/` — разложенные view и URL-модули.
- `apps/leave/services/schedule_drafts/` — сервисы черновика графика отпусков.
- `apps/leave/ml/` — neural scoring, обучение, traces и JSON-артефакты модели.
- `templates/` — общие HTML-шаблоны проекта.
- `templates/includes/` — маленькие partial-шаблоны по подпапкам.
- `static/css/` — стили по слоям: `base`, `auth`, `layout`, `components`,
  `pages`.
- `static/js/` — JavaScript по зонам: `core`, `auth`, `components`, `pages`,
  `schedule`, `calendar`.

## Быстрый Старт

1. Создай файл `.env` по примеру `.env.example`.
2. Установи зависимости через виртуальное окружение проекта:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

3. Примени миграции:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

4. Для локальной проверки запусти сервер через helper:

```powershell
.\scripts\django_server.ps1 -Action restart -Port 8001 -ReadyTimeoutSeconds 10
```

## Демо-Данные

Полное пересоздание demo-БД:

```powershell
.\.venv\Scripts\python.exe manage.py seed_vacation_requests --confirm-reset --seed-value 42
```

Команда удаляет и пересоздает demo-данные, поэтому перед запуском в уже
настроенной локальной БД нужно отдельно подтвердить, что это действительно
нужно.

Подробный контекст для переноса на другой компьютер и продолжения в новом чате:

- `AGENTS.md`
- `ARCHITECTURE.md`
- `WORK_SUMMARY.md`
- `NEURAL_MODULE_PLAN.md`
