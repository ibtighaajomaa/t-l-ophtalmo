#!/bin/bash
set -e

echo "=== Waiting for Keycloak ==="
python /app/wait_for_kc.py

echo "=== Initializing Keycloak ==="
python /app/init_kc.py

echo "=== Running migrations ==="
python /app/manage.py migrate --noinput

echo "=== Creating superuser (if not exists) ==="
python /app/manage.py createsuperuser --noinput --username "$DJANGO_SUPERUSER_USERNAME" --email "$DJANGO_SUPERUSER_EMAIL" 2>/dev/null || true

echo "=== Collecting static files ==="
python /app/manage.py collectstatic --noinput

echo "=== Starting Gunicorn ==="
exec gunicorn --bind 0.0.0.0:8001 --timeout 300 config.wsgi:application
