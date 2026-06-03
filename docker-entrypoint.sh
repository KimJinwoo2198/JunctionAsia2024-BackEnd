#!/bin/bash
set -e

echo "Waiting for database..."
python << 'END'
import os
import sys
import time


def wait_for_db():
    if not os.getenv("POSTGRES_NAME"):
        print("Using SQLite database, skipping PostgreSQL wait.")
        return True

    try:
        import psycopg
    except ImportError:
        print("psycopg is not installed, skipping PostgreSQL wait.")
        return True

    max_attempts = 30
    for attempt in range(1, max_attempts + 1):
        try:
            conn = psycopg.connect(
                host=os.getenv("POSTGRES_HOST", "db"),
                port=os.getenv("POSTGRES_PORT", "5432"),
                user=os.getenv("POSTGRES_USER", "postgres"),
                password=os.getenv("POSTGRES_PASSWORD", "postgres"),
                dbname=os.getenv("POSTGRES_NAME", "postgres"),
                connect_timeout=5,
            )
            conn.close()
            print("Database is ready.")
            return True
        except Exception as exc:
            print(f"Waiting for database... ({attempt}/{max_attempts}) {exc}")
            time.sleep(2)

    print("Database connection failed.")
    return False


if not wait_for_db():
    sys.exit(1)
END

echo "Running migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput || true

if [ "$CREATE_SUPERUSER" = "true" ]; then
    echo "Creating superuser..."
    python manage.py shell << 'END'
from Users.models import CustomUser
import os

if not CustomUser.objects.filter(is_superuser=True).exists():
    CustomUser.objects.create_superuser(
        username=os.getenv("SUPERUSER_USERNAME", "admin"),
        email=os.getenv("SUPERUSER_EMAIL", "admin@example.com"),
        password=os.getenv("SUPERUSER_PASSWORD", "admin1234"),
    )
    print("Superuser created.")
else:
    print("Superuser already exists.")
END
fi

exec "$@"
