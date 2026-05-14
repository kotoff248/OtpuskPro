# Kabinet.pro

Веб-приложение на Django для управления отпусками, графиком отпусков,
согласованиями и кадровым планированием.

## Структура проекта

- `manage.py` — точка входа Django.
- `config/` — маршруты проекта, `ASGI/WSGI` и настройки.
- `config/settings/base.py` — общие настройки проекта.
- `config/settings/postgres.py` — конфигурация PostgreSQL.
- `apps/accounts/` — вход в систему и привязка сотрудников к `django.contrib.auth`.
- `apps/core/` — общие сигналы и management-команды.
- `apps/employees/` — сотрудники, отделы, формы и профили.
- `apps/leave/` — заявки на отпуск, календарь, согласование и аналитика.
- `templates/` — общие HTML-шаблоны проекта.
- `static/` — общие стили и JavaScript.

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
- `WORK_SUMMARY.md`
- `NEURAL_MODULE_PLAN.md`
