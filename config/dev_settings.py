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

# Allow any host in local/dev use (accessed via a domain/reverse proxy)
ALLOWED_HOSTS = ['*']
CSRF_TRUSTED_ORIGINS = ['http://aboahmed.zan-iraq.com', 'https://aboahmed.zan-iraq.com']
