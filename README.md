# Project Template

## 시작하기

### 필요 조건
- Python 3.8+
- pip
- virtualenv (선택사항이지만 권장)

### 설치 및 설정

1. 저장소 클론:
   ```
   git clone https://github.com/JunctionAsia2024-0xC0FFEE/BackEnd.git
   cd BackEnd
   ```

2. 가상 환경 생성 및 활성화:
   ```
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   ```

3. 의존성 설치:
   ```
   pip install -r requirements.txt
   ```

4. 설정 확인:
   - 모든 설정은 `project_template/settings.py`에 포함되어 있습니다.
   - 필요한 경우 `settings.py`를 직접 수정하여 환경을 구성하세요.

5. 데이터베이스 마이그레이션:
   ```
   python manage.py migrate
   ```

6. 관리자 계정 생성:
   ```
   python manage.py createsuperuser
   ```

### 실행

개발 서버 실행:
```
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

## 주의사항

- 이 프로젝트는 별도의 `.env` 파일을 사용하지 않습니다. 따라서, 모든 설정은 `settings.py`에서 직접 관리됩니다.