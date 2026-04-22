# OtpuskPro

Веб-приложение на Django для учета отпусков.

## Что есть в проекте

- `app/` - Django-проект и основное приложение
- `requirements.txt` - зависимости Python
- `scripts/` - вспомогательные скрипты

## Быстрый старт

1. Создать и активировать виртуальное окружение.
2. Установить зависимости:

```bash
pip install -r requirements.txt
```

3. Создать файл `app/.env` по примеру `app/.env.example` и заполнить параметры базы данных PostgreSQL.
4. Перейти в папку `app/` и выполнить миграции:

```bash
python manage.py migrate
```

5. Запустить сервер разработки:

```bash
python manage.py runserver
```
