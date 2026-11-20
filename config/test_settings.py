"""
Django test settings.

Default: SQLite in memory + local files (fast, no services needed).
In Docker (`docker compose --profile test run --rm test`) the same suite runs
against the real stack: TEST_DB=postgres uses PostgreSQL (row locks are real
there), and USE_S3=True stores files in MinIO under a throwaway prefix.
"""
import os
import uuid

os.environ.setdefault('DEBUG', 'True')
os.environ.setdefault('DEBUG_TOOLBAR', 'False')

from .settings import *  # noqa: E402,F401,F403

if os.environ.get('TEST_DB') != 'postgres':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': ':memory:',
        }
    }

# The test client speaks plain HTTP: never redirect to HTTPS or require
# secure cookies, even when the environment (.env in Docker) says DEBUG=False.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0

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
    'default': STORAGES['default'] if USE_S3 else {  # noqa: F405
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
if USE_S3:  # noqa: F405
    # Each run writes under its own prefix in the bucket
    STORAGES['default'] = {
        **STORAGES['default'],
        'OPTIONS': {**STORAGES['default']['OPTIONS'], 'location': f'test-runs/{uuid.uuid4().hex[:12]}'},
    }
