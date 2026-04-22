# OtpuskPro

Веб-приложение на Django для управления отпусками сотрудников.

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

## Быстрый старт

1. Создай файл `.env` по примеру `.env.example`.
2. Установи зависимости:

```bash
pip install -r requirements.txt
```

3. Примени миграции:

```bash
python manage.py migrate
```

4. Запусти сервер разработки:

```bash
python manage.py runserver
```

Для Windows доступен вспомогательный скрипт:

```powershell
.\run_postgres.ps1
```
