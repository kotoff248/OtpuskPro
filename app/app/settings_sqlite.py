from .settings_base import *  # noqa: F403


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "backups" / "sqlite_source.db",  # noqa: F405
    }
}
