"""
Local development settings: SQLite, DEBUG on.

    DJANGO_SETTINGS_MODULE=config.dev_settings python manage.py runserver

Production uses config.settings with environment variables (see .env.example).
"""
import os

os.environ.setdefault('DEBUG', 'True')  # must be set before settings are evaluated

from .settings import *  # noqa: E402,F401,F403
from decouple import Csv, config  # noqa: E402

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',  # noqa: F405
    }
}

DEBUG = True
# Accessed through a LAN IP / tunnel while developing.
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='*', cast=Csv())
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='', cast=Csv())
