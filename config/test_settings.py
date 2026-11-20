"""
Django test settings for Construction ERP project.
Uses SQLite for faster test execution.
"""
import os

os.environ.setdefault('DEBUG', 'True')
os.environ.setdefault('DEBUG_TOOLBAR', 'False')

from .settings import *  # noqa: E402,F401,F403

# Use SQLite for testing
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Disable debug toolbar in tests
INSTALLED_APPS = [app for app in INSTALLED_APPS if app != 'debug_toolbar']
MIDDLEWARE = [m for m in MIDDLEWARE if 'debug_toolbar' not in m]

# Speed up password hashing in tests
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Quiet logging in tests
LOGGING = {'version': 1, 'disable_existing_loggers': False}

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
