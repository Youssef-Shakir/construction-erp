"""
Django development settings for Construction ERP project.
Uses SQLite for local development without PostgreSQL.
"""
from .settings import *  # noqa: F401, F403

# Use SQLite for development
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Debug settings
DEBUG = True
