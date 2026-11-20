#!/bin/sh
# Container entrypoint: optional migrations + first admin, then exec the command.
set -e

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    echo "entrypoint: applying migrations"
    python manage.py migrate --noinput
fi

# Create the first admin once (DJANGO_SUPERUSER_EMAIL/PASSWORD/FIRST_NAME/LAST_NAME).
if [ -n "${DJANGO_SUPERUSER_EMAIL:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
    python manage.py shell --verbosity 0 -c "
import os
from django.contrib.auth import get_user_model
U = get_user_model()
email = os.environ['DJANGO_SUPERUSER_EMAIL']
if not U.objects.filter(email=email).exists():
    U.objects.create_superuser(
        email=email, password=os.environ['DJANGO_SUPERUSER_PASSWORD'],
        first_name=os.environ.get('DJANGO_SUPERUSER_FIRST_NAME', 'Admin'),
        last_name=os.environ.get('DJANGO_SUPERUSER_LAST_NAME', ''),
    )
    print('entrypoint: created admin', email)
"
fi

exec "$@"
