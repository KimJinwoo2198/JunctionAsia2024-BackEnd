# 멀티스테이지 빌드를 사용한 최적화된 Dockerfile
FROM python:3.11-slim as builder

# 빌드 의존성 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# 작업 디렉토리 설정
WORKDIR /app

# Python 의존성 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# 프로덕션 스테이지
FROM python:3.11-slim

# 런타임 의존성 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    libmagic1 \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# 빌더 스테이지에서 Python 패키지 복사
COPY --from=builder /root/.local /root/.local

# 환경 변수 설정
ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=project_template.settings

# 작업 디렉토리 설정
WORKDIR /app

# 프로젝트 파일 복사
COPY . .

# 정적 파일 수집을 위한 디렉토리 생성
RUN mkdir -p /app/staticfiles /app/media

# 포트 노출
EXPOSE 8000

# 헬스체크 설정 (docker-compose에서 오버라이드)
# HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
#     CMD python -c "import requests; requests.get('http://localhost:8000/admin/', timeout=5)" || exit 1

# 실행 스크립트
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["gunicorn", "project_template.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "120"]

