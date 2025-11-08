#!/bin/bash
set -e

# 데이터베이스 연결 대기
echo "Waiting for database..."
python << END
import sys
import time
import os

def wait_for_db():
    max_attempts = 30
    attempt = 0
    
    # PostgreSQL 사용 여부 확인
    if not os.getenv('POSTGRES_NAME'):
        print("Using SQLite database, skipping wait...")
        return True
    
    try:
        import psycopg2
    except ImportError:
        print("psycopg2 not installed, skipping PostgreSQL wait...")
        return True
    
    while attempt < max_attempts:
        try:
            conn = psycopg2.connect(
                host=os.getenv('POSTGRES_HOST', 'db'),
                port=os.getenv('POSTGRES_PORT', '5432'),
                user=os.getenv('POSTGRES_USER', 'postgres'),
                password=os.getenv('POSTGRES_PASSWORD', 'postgres'),
                dbname=os.getenv('POSTGRES_NAME', 'postgres')
            )
            conn.close()
            print("Database is ready!")
            return True
        except Exception as e:
            attempt += 1
            print(f"Waiting for database... ({attempt}/{max_attempts})")
            time.sleep(2)
    
    print("Database connection failed!")
    return False

if not wait_for_db():
    sys.exit(1)
END

# Django 마이그레이션 실행
echo "Running migrations..."
python manage.py migrate --noinput

# 정적 파일 수집
echo "Collecting static files..."
python manage.py collectstatic --noinput || true

# 관리자 계정 생성 (환경변수로 제어)
if [ "$CREATE_SUPERUSER" = "true" ]; then
    echo "Creating superuser..."
    python manage.py shell << END
from Users.models import CustomUser
import os

if not CustomUser.objects.filter(is_superuser=True).exists():
    CustomUser.objects.create_superuser(
        email=os.getenv('SUPERUSER_EMAIL', 'admin@example.com'),
        password=os.getenv('SUPERUSER_PASSWORD', 'admin1234'),
    )
    print("Superuser created!")
else:
    print("Superuser already exists.")
END
fi

# 명령 실행
exec "$@"

