# Project Template

## 시작하기

### Docker를 사용한 실행 (권장)

#### 필요 조건
- Docker 20.10+
- Docker Compose 2.0+

#### 빠른 시작

1. 저장소 클론:
   ```bash
   git clone https://github.com/JunctionAsia2024-0xC0FFEE/BackEnd.git
   cd BackEnd
   ```

2. 환경 변수 파일 생성:
   ```bash
   cp env.example .env
   ```
   `.env` 파일을 열어 필요한 값들을 설정하세요 (특히 `DJANGO_SECRET_KEY`, `OPENAI_API_KEY` 등).

3. Docker Compose로 서비스 시작:
   ```bash
   docker-compose up -d
   ```

4. 로그 확인:
   ```bash
   docker-compose logs -f web
   ```

5. 관리자 계정 생성 (선택사항):
   ```bash
   docker-compose exec web python manage.py createsuperuser
   ```
   또는 `.env` 파일에서 `CREATE_SUPERUSER=true`로 설정하고 `SUPERUSER_EMAIL`, `SUPERUSER_PASSWORD`를 설정한 후 컨테이너를 재시작하세요.

서버는 기본적으로 http://localhost:8000 에서 실행됩니다.

#### Docker 명령어

- 서비스 시작: `docker-compose up -d`
- 서비스 중지: `docker-compose stop`
- 서비스 종료 및 삭제: `docker-compose down`
- 로그 확인: `docker-compose logs -f [service_name]`
- 컨테이너 재빌드: `docker-compose build --no-cache`
- Django 명령 실행: `docker-compose exec web python manage.py [command]`

### 로컬 개발 환경 설정

#### 필요 조건
- Python 3.11+
- pip
- virtualenv (선택사항이지만 권장)
- PostgreSQL 16+ (선택사항, SQLite도 사용 가능)
- MongoDB 7.0+ (선택사항)

#### 설치 및 설정

1. 저장소 클론:
   ```bash
   git clone https://github.com/JunctionAsia2024-0xC0FFEE/BackEnd.git
   cd BackEnd
   ```

2. 가상 환경 생성 및 활성화:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   ```

3. 의존성 설치:
   ```bash
   pip install -r requirements.txt
   ```

4. 환경 변수 설정:
   - `env.example` 파일을 참고하여 `.env` 파일을 생성하거나
   - 환경 변수를 직접 설정하세요.

5. 데이터베이스 마이그레이션:
   ```bash
   python manage.py migrate
   ```

6. 관리자 계정 생성:
   ```bash
   python manage.py createsuperuser
   ```

#### 실행

개발 서버 실행:
```bash
python manage.py runserver
```

서버는 기본적으로 http://localhost:8000 에서 실행됩니다.

## 주요 명령어

- 마이그레이션 생성:
  ```
  python manage.py makemigrations
  ```

- 마이그레이션 적용:
  ```
  python manage.py migrate
  ```

- 정적 파일 수집:
  ```
  python manage.py collectstatic
  ```

- 테스트 실행:
  ```
  python manage.py test
  ```

## API 문서

Swagger UI를 통한 API 문서는 메인 페이지(`/`)에서 확인할 수 있습니다.

## 추가 설정

### MongoDB
MongoDB 연결 설정은 `settings.py`의 `MONGODB_URI`와 `MONGODB_NAME`에서 확인 및 수정할 수 있습니다. ( 혹시 몰라서 이중 데이터베이스 사용 )

## 문제 해결

- 마이그레이션 관련 문제 발생 시:
  ```
  python manage.py makemigrations Users
  python manage.py migrate Users
  python manage.py migrate
  ```

- 정적 파일 로드 문제 발생 시:
  ```
  python manage.py collectstatic --noinput
  ```

## Docker 아키텍처

이 프로젝트는 Docker Compose를 사용하여 다음 서비스들을 관리합니다:

- **web**: Django 애플리케이션 (Gunicorn으로 실행)
- **db**: PostgreSQL 데이터베이스
- **mongo**: MongoDB 데이터베이스

모든 서비스는 `junction_network`라는 브리지 네트워크를 통해 통신합니다.

## 주의사항

- 프로덕션 환경에서는 반드시 `.env` 파일의 `DJANGO_SECRET_KEY`를 변경하세요.
- 프로덕션 환경에서는 `DJANGO_DEBUG=false`로 설정하세요.
- 데이터베이스 볼륨은 `docker-compose down -v`를 실행하면 삭제됩니다. 중요한 데이터는 백업하세요.
- 환경 변수는 `env.example` 파일을 참고하여 `.env` 파일로 관리할 수 있습니다.