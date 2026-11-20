"""
Django settings for Construction ERP project.
"""
import importlib.util
from pathlib import Path

from decouple import Csv, config
from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Safe by default: production unless DEBUG=True is set explicitly (.env for dev).
DEBUG = config('DEBUG', default=False, cast=bool)

_INSECURE_KEY = 'django-insecure-dev-only-key-do-not-use-in-production'
SECRET_KEY = config('SECRET_KEY', default=_INSECURE_KEY if DEBUG else '')
if not SECRET_KEY or (not DEBUG and SECRET_KEY == _INSECURE_KEY):
    raise ImproperlyConfigured(
        'SECRET_KEY must be set in production. Generate one with: '
        'python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"'
    )

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='', cast=Csv())

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third party
    'simple_history',

    # Local apps
    'apps.accounts',
    'apps.core',
    'apps.projects',
    'apps.accounting',
    'apps.advances',
    'apps.expenses',
    'apps.invoicing',
    'apps.payments',
    'apps.dashboard',
]

MIDDLEWARE = [
    'apps.core.middleware.HealthCheckMiddleware',  # first: answers /healthz/ before host/SSL checks
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'simple_history.middleware.HistoryRequestMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='construction_erp'),
        'USER': config('DB_USER', default='postgres'),
        'PASSWORD': config('DB_PASSWORD', default='postgres'),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
        'CONN_MAX_AGE': config('DB_CONN_MAX_AGE', default=60, cast=int),
        'CONN_HEALTH_CHECKS': True,
    }
}

# Custom User Model
AUTH_USER_MODEL = 'accounts.User'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization - Arabic RTL
LANGUAGE_CODE = 'ar'
TIME_ZONE = 'Asia/Riyadh'
USE_I18N = True
USE_TZ = True

LANGUAGES = [
    ('ar', 'العربية'),
    ('en', 'English'),
]

LOCALE_PATHS = [
    BASE_DIR / 'locale',
]

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': (
            'django.contrib.staticfiles.storage.StaticFilesStorage' if DEBUG
            else 'whitenoise.storage.CompressedManifestStaticFilesStorage'
        ),
    },
}

# Uploaded files on S3-compatible storage (MinIO in Docker, or AWS S3).
# The bucket stays PRIVATE: every download goes through Django's permission
# check (core:attachment_download), never a public bucket URL.
USE_S3 = config('USE_S3', default=False, cast=bool)
if USE_S3:
    STORAGES['default'] = {
        'BACKEND': 'storages.backends.s3.S3Storage',
        'OPTIONS': {
            'bucket_name': config('AWS_STORAGE_BUCKET_NAME'),
            'endpoint_url': config('AWS_S3_ENDPOINT_URL', default=None),  # http://minio:9000
            'access_key': config('AWS_ACCESS_KEY_ID'),
            'secret_key': config('AWS_SECRET_ACCESS_KEY'),
            'region_name': config('AWS_S3_REGION_NAME', default='us-east-1'),
            'addressing_style': config('AWS_S3_ADDRESSING_STYLE', default='path'),  # MinIO needs path
            'signature_version': 's3v4',
            'location': config('AWS_LOCATION', default=''),
            'default_acl': None,          # bucket policy decides (private)
            'file_overwrite': False,
            'querystring_auth': True,
            'querystring_expire': 300,
        },
    }

# Media files (uploads). Attachments are NOT served from MEDIA_URL in
# production - they go through core:attachment_download (permission check).
MEDIA_URL = 'media/'
MEDIA_ROOT = Path(config('MEDIA_ROOT', default=str(BASE_DIR / 'media')))

# Attachments / scanners
ATTACHMENT_MAX_UPLOAD_MB = config('ATTACHMENT_MAX_UPLOAD_MB', default=25, cast=int)
ATTACHMENT_IMAGE_MAX_DIMENSION = config('ATTACHMENT_IMAGE_MAX_DIMENSION', default=2800, cast=int)
# Folder the office scanner writes to ("scan to folder"); see `manage.py import_scans`.
SCAN_INBOX_DIR = config('SCAN_INBOX_DIR', default='')
# Behind nginx: internal location mapped to MEDIA_ROOT, e.g. /protected-media/
ATTACHMENT_X_ACCEL_PREFIX = config('ATTACHMENT_X_ACCEL_PREFIX', default='')
# Compress scanned PDFs with Ghostscript: ebook (150 dpi) | printer (300 dpi) | screen | off
ATTACHMENT_PDF_COMPRESSION = config('ATTACHMENT_PDF_COMPRESSION', default='ebook')
ATTACHMENT_PDF_COMPRESS_MIN_KB = config('ATTACHMENT_PDF_COMPRESS_MIN_KB', default=300, cast=int)
DATA_UPLOAD_MAX_NUMBER_FILES = 50
FILE_UPLOAD_PERMISSIONS = 0o640

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Login/Logout URLs
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'dashboard:home'
LOGOUT_REDIRECT_URL = 'accounts:login'

# Session settings
SESSION_COOKIE_AGE = config('SESSION_COOKIE_AGE', default=8 * 3600, cast=int)  # one working day
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# Security headers / HTTPS (active whenever DEBUG is off)
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
    SESSION_COOKIE_SECURE = config('SECURE_COOKIES', default=True, cast=bool)
    CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
    # Turn on once HTTPS is confirmed working everywhere (e.g. 31536000).
    SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=0, cast=int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = config('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False, cast=bool)

# Logging: everything to stdout (journald / docker collect it)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'plain': {'format': '%(asctime)s %(levelname)s %(name)s: %(message)s'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'plain'},
    },
    'root': {'handlers': ['console'], 'level': config('LOG_LEVEL', default='INFO')},
    'loggers': {
        'django.request': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
    },
}

# Messages
from django.contrib.messages import constants as messages
MESSAGE_TAGS = {
    messages.DEBUG: 'debug',
    messages.INFO: 'info',
    messages.SUCCESS: 'success',
    messages.WARNING: 'warning',
    messages.ERROR: 'error',
}

# Debug toolbar (only in development, and only if installed)
if DEBUG and importlib.util.find_spec('debug_toolbar') and config('DEBUG_TOOLBAR', default=True, cast=bool):
    INSTALLED_APPS += ['debug_toolbar']
    MIDDLEWARE.insert(0, 'debug_toolbar.middleware.DebugToolbarMiddleware')
    INTERNAL_IPS = ['127.0.0.1']
SESSION_COOKIE_SAMESITE = 'Lax'  # relied on by the PWA share target (csrf_exempt)
