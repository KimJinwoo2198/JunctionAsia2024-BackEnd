import logging
import random
import requests
from datetime import timedelta
from urllib.parse import urlencode
import pyotp
import qrcode
import base64
from io import BytesIO

from rest_framework import status
from rest_framework.views import APIView
from django.core.files import File
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.db import transaction
from django.conf import settings
from django.contrib.auth import logout,get_user_model
from django.core.cache import cache
from django.utils import timezone

from .serializers import CustomUserCreationSerializer, CustomAuthTokenSerializer, PasswordChangeSerializer, CallbackUserInfoSerializer, Enable2FASerializer, Verify2FASerializer
from .exceptions import AccountLockedException, TooManyAttemptsException, GoogleAPIError, UserCreationError
from .models import EmailVerification, LoginHistory, CustomUser
from .tasks import send_verification_email, save_user_to_mongodb, send_security_alert, get_location_from_ip
from .utils import parse_user_agent

logger = logging.getLogger(__name__)
User = get_user_model()

class SignupView(APIView):
    permission_classes = [AllowAny]
    @swagger_auto_schema(
        operation_summary="회원가입",
        operation_description="새로운 사용자를 등록합니다.",
        request_body=CustomUserCreationSerializer,
        tags=['User'],
        responses={
            201: openapi.Response(
                description="회원가입 성공",
                examples={
                    "application/json": {
                        "status": "success",
                        "message": "회원가입이 완료되었습니다. 이메일로 전송된 인증번호를 입력해주세요.",
                        "data": {"user_id": 1}
                    }
                }
            ),
            400: openapi.Response(
                description="잘못된 입력",
                examples={
                    "application/json": {
                        "status": "error",
                        "message": "입력 데이터가 유효하지 않습니다.",
                        "errors": {
                            "username": ["이미 사용 중인 사용자 이름입니다."],
                            "email": ["이미 등록된 이메일 주소입니다."],
                            "password": ["비밀번호가 너무 짧습니다. 최소 8자 이상이어야 합니다."],
                            "phone_number": ["올바른 전화번호 형식이 아닙니다. 예: 010-1234-5678"]
                        }
                    }
                }
            ),
            500: openapi.Response(
                description="서버 에러",
                examples={
                    "application/json": {
                        "status": "error",
                        "message": "회원가입 중 오류가 발생했습니다. 다시 시도해주세요.",
                        "errors": ["내부 서버 오류가 발생했습니다."]
                    }
                }
            )
        }
    )
    def post(self, request):
        serializer = CustomUserCreationSerializer(data=request.data)
        if serializer.is_valid():
            try:
                user = serializer.save()
                
                # 인증 번호 생성 및 저장
                verification_code = str(random.randint(100000, 999999))
                EmailVerification.objects.create(user=user, code=verification_code)
                
                # 비동기로 이메일 전송
                send_verification_email(user.email, verification_code)
                
                # 비동기로 MongoDB에 사용자 정보 저장
                save_user_to_mongodb(user.id)
                
                return Response({
                    "status": "success",
                    "message": "회원가입이 완료되었습니다. 이메일로 전송된 인증번호를 입력해주세요.",
                    "data": {"user_id": user.id}
                }, status=status.HTTP_201_CREATED)
            except Exception as e:
                logger.error(f"회원가입 중 오류 발생: {str(e)}")
                return Response({
                    "status": "error",
                    "message": "회원가입 중 오류가 발생했습니다. 다시 시도해주세요.",
                    "errors": [str(e)]
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            return Response({
                "status": "error",
                "message": "입력 데이터가 유효하지 않습니다.",
                "errors": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

class LoginView(APIView):
    permission_classes = [AllowAny]
    serializer_class = CustomAuthTokenSerializer

    @swagger_auto_schema(
        operation_summary="로그인",
        operation_description="사용자 로그인 및 JWT 토큰 발급",
        request_body=CustomAuthTokenSerializer,
        tags=['User'],
        responses={
            200: openapi.Response(
                description="로그인 성공",
                examples={
                    "application/json": {
                        "status": "success",
                        "message": "로그인 성공",
                        "tokens": {
                            "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
                            "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
                        }
                    }
                }
            ),
            202: openapi.Response(
                description="2차 인증 필요",
                examples={
                    "application/json": {
                        "status": "success",
                        "message": "로그인 성공. 2차 인증 토큰을 입력하세요.",
                        "data": {"user_id": 1}
                    }
                }
            ),
            400: openapi.Response(description="잘못된 입력"),
            401: openapi.Response(description="인증 실패"),
            403: openapi.Response(description="계정 잠김"),
            429: openapi.Response(description="과도한 로그인 시도"),
        }
    )
    def post(self, request, *args, **kwargs):
        ip = self.get_client_ip(request)
        login_attempts = cache.get(f'login_attempts_{ip}', 0)
        
        if login_attempts >= 5:
            raise TooManyAttemptsException()

        serializer = self.serializer_class(data=request.data, context={'request': request})
        try:
            serializer.is_valid(raise_exception=True)
            user = serializer.validated_data['user']
            
            if user.is_locked:
                raise AccountLockedException()

            # 비밀번호 변경 요구 (60일마다)
            if user.last_password_change < timezone.now() - timedelta(days=60):
                return Response({"message": "비밀번호를 변경해야 합니다."}, status=status.HTTP_403_FORBIDDEN)

            refresh = RefreshToken.for_user(user)
            
            # 로그인 성공 처리
            cache.delete(f'login_attempts_{ip}')
            user.failed_login_attempts = 0
            user.save()
            
            # 위치 정보 가져오기
            location = get_location_from_ip(ip)
            logger.info(f"User: {user}, IP: {ip}, Location: {location}")
            
            # 로그인 시간 가져오기
            login_time = timezone.now().strftime("%Y년 %m월 %d일 %H:%M")
            
            # 기기 정보 가져오기
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            device_info = parse_user_agent(user_agent)
            
            # 로그인 히스토리 기록
            login_history = LoginHistory.objects.create(
                user=user,
                ip_address=ip,
                user_agent=user_agent,
                success=True,
                location=location or "Unknown Location"
            )

            # 새로운 위치에서의 로그인 감지
            if self.is_new_location(user, location):
                send_security_alert(
                    email=user.email,
                    username=user.username,
                    login_location=location,
                    login_time=login_time,
                    device_info=device_info
                )

            logger.info(f"User {user.username} logged in successfully from {location}")
            
            if user.is_2fa_enabled:
                # 2차 인증 필요 메시지 반환
                return Response({
                    "status": "success",
                    "message": "로그인 성공. 2차 인증 토큰을 입력하세요.",
                    "data": {"user_id": user.id}
                }, status=status.HTTP_202_ACCEPTED)

            return Response({
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            })
        except Exception as e:
            # 로그인 실패 처리
            cache.set(f'login_attempts_{ip}', login_attempts + 1, 300)
            
            if isinstance(serializer.instance, User):
                user = serializer.instance
                user.failed_login_attempts += 1
                if user.failed_login_attempts >= 5:
                    user.is_locked = True
                    send_security_alert(
                        email=user.email,
                        username=user.username,
                        login_location="Unknown",
                        login_time=timezone.now().strftime("%Y년 %m월 %d일 %H:%M"),
                        device_info="Unknown",
                        custom_message="계정이 잠겼습니다. 보안 질문을 통해 잠금을 해제하세요."
                    )
                user.save()

                LoginHistory.objects.create(
                    user=user,
                    ip_address=ip,
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    success=False,
                    location=get_location_from_ip(ip)
                )
            
            logger.warning(f"Failed login attempt for username: {request.data.get('username')}, IP: {ip}")
            raise

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

    def is_new_location(self, user, location):
        recent_logins = LoginHistory.objects.filter(user=user, success=True).order_by('-login_time')[:5]
        return location not in [login.location for login in recent_logins]
   
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_summary="로그아웃",
        tags=['User'],
        responses={
            200: openapi.Response(
                description="로그아웃 성공",
                examples={
                    "application/json": {
                        "status": "success",
                        "message": "성공적으로 로그아웃되었습니다.",
                        "data": {
                            "username": "user@example.com",
                            "logout_time": "2024-08-01T12:34:56Z"
                        }
                    }
                }
            ),
            400: openapi.Response(
                description="잘못된 요청",
                examples={
                    "application/json": {
                        "status": "error",
                        "message": "로그아웃 처리 중 오류가 발생했습니다.",
                        "errors": ["유효하지 않은 토큰입니다."]
                    }
                }
            ),
            401: openapi.Response(
                description="인증 실패",
                examples={
                    "application/json": {
                        "status": "error",
                        "message": "유효한 인증 정보가 제공되지 않았습니다.",
                        "errors": ["인증 토큰이 누락되었거나 만료되었습니다."]
                    }
                }
            ),
        }
    )
    def post(self, request):
        try:
            refresh_token = request.data.get('refresh_token')
            if not refresh_token:
                return Response({
                    "status": "error",
                    "message": "Refresh 토큰이 제공되지 않았습니다.",
                    "errors": ["Refresh 토큰은 필수입니다."]
                }, status=status.HTTP_400_BAD_REQUEST)

            token = RefreshToken(refresh_token)
            token.blacklist()

            user = request.user
            if isinstance(user, CustomUser):
                user.last_logout = timezone.now()
                user.save(update_fields=['last_logout'])

            logger.info(f"User {user.username} logged out successfully at {user.last_logout}")

            return Response({
                "status": "success",
                "message": "성공적으로 로그아웃되었습니다.",
                "data": {
                    "username": user.username,
                    "logout_time": user.last_logout.isoformat() if user.last_logout else None
                }
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Logout error for user {request.user.username}: {str(e)}")
            return Response({
                "status": "error",
                "message": "로그아웃 처리 중 오류가 발생했습니다.",
                "errors": [str(e)]
            }, status=status.HTTP_400_BAD_REQUEST)
            
class PasswordChangeView(APIView):
    serializer_class = PasswordChangeSerializer
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_summary="비밀번호 변경",
        operation_description="비밀번호 변경",
        request_body=PasswordChangeSerializer,
        tags=['User'],
        responses={
            200: openapi.Response(description="비밀번호 변경 성공"),
            400: openapi.Response(description="잘못된 입력"),
        }
    )
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            user = request.user
            if user.check_password(serializer.validated_data['old_password']):
                user.set_password(serializer.validated_data['new_password'])
                user.last_password_change = timezone.now()
                user.save()
                return Response({"message": "비밀번호가 성공적으로 변경되었습니다."})
            return Response({"error": "현재 비밀번호가 일치하지 않습니다."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UnlockAccountView(APIView):
    permission_classes = [IsAuthenticated]
    
    @swagger_auto_schema(
        operation_summary="계정 잠금 해제",
        operation_description="계정 잠금 해제",
        tags=['User'],
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'username': openapi.Schema(type=openapi.TYPE_STRING),
                'security_answer': openapi.Schema(type=openapi.TYPE_STRING),
            }
        ),
        responses={
            200: openapi.Response(description="계정 잠금 해제 성공"),
            400: openapi.Response(description="잘못된 입력"),
        }
    )
    def post(self, request):
        username = request.data.get('username')
        security_answer = request.data.get('security_answer')

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return Response({"error": "사용자를 찾을 수 없습니다."}, status=status.HTTP_400_BAD_REQUEST)

        if user.security_answer == security_answer:
            user.is_locked = False
            user.failed_login_attempts = 0
            user.save()
            return Response({"message": "계정 잠금이 해제되었습니다."})
        else:
            return Response({"error": "보안 질문의 답변이 일치하지 않습니다."}, status=status.HTTP_400_BAD_REQUEST)
        
class GoogleLoginView(APIView):
    permission_classes = [AllowAny]

    @swagger_auto_schema(
        operation_summary="Google 로그인 URL 생성",
        operation_description="Google OAuth2 로그인 프로세스를 시작하기 위한 URL을 생성합니다. "
                              "이 URL로 사용자를 리디렉션하면 Google 로그인 페이지가 표시됩니다.",
        tags=['User'],
        responses={
            200: openapi.Response(
                description="성공적으로 URL 생성",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'login_url': openapi.Schema(
                            type=openapi.TYPE_STRING,
                            description="Google 로그인 페이지 URL"
                        )
                    }
                ),
                examples={
                    "application/json": {
                        "login_url": "https://accounts.google.com/o/oauth2/v2/auth?client_id=your_client_id&redirect_uri=your_redirect_uri&response_type=code&scope=email profile&access_type=offline&prompt=select_account"
                    }
                }
            )
        },
    )
    def get(self, request):
        google_login_url = "https://accounts.google.com/o/oauth2/v2/auth"
        
        params = {
            'client_id': settings.GOOGLE_CLIENT_ID,
            'redirect_uri': settings.GOOGLE_REDIRECT_URI,
            'response_type': 'code',
            'scope': 'email profile',
            'access_type': 'offline',
            'prompt': 'select_account'
        }
        
        auth_url = f"{google_login_url}?{urlencode(params)}"
        
        return Response({"login_url": auth_url})
    
class GoogleCallbackView(APIView):
    permission_classes = [AllowAny]

    @swagger_auto_schema(
        operation_summary="Google OAuth 콜백",
        operation_description="Handle Google OAuth callback and user authentication",
        query_serializer=CallbackUserInfoSerializer,
        tags=['User'],
        responses={
            200: openapi.Response(
                description="Successful authentication",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'access_token': openapi.Schema(type=openapi.TYPE_STRING),
                        'refresh_token': openapi.Schema(type=openapi.TYPE_STRING),
                        'user': openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            properties={
                                'id': openapi.Schema(type=openapi.TYPE_INTEGER),
                                'email': openapi.Schema(type=openapi.TYPE_STRING),
                                'is_new_user': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                            }
                        )
                    }
                )
            ),
            400: "Bad Request",
            401: "Unauthorized",
            500: "Internal Server Error"
        }
    )
    def get(self, request):
        try:
            code = request.query_params.get('code')
            if not code:
                return Response({"error": "Authorization code is required"}, status=status.HTTP_400_BAD_REQUEST)

            google_user = self.get_google_user(code)
            user = self.get_or_create_user(google_user)
            tokens = self.get_tokens_for_user(user)
            
            response_data = {
                'access_token': tokens['access'],
                'refresh_token': tokens['refresh'],
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'is_new_user': user.date_joined == user.last_login
                }
            }
            return Response(response_data, status=status.HTTP_200_OK)

        except GoogleAPIError as e:
            logger.error(f"Google API error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_401_UNAUTHORIZED)
        except UserCreationError as e:
            logger.error(f"User creation error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("Unexpected error in Google callback")
            return Response({"error": "An unexpected error occurred"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def get_google_user(self, code):
        token = self.get_google_token(code)
        user_info = self.get_google_user_info(token)
        return user_info

    def get_google_token(self, code):
        data = {
            'code': code,
            'client_id': settings.GOOGLE_CLIENT_ID,
            'client_secret': settings.GOOGLE_CLIENT_SECRET,
            'redirect_uri': settings.GOOGLE_REDIRECT_URI,
            'grant_type': 'authorization_code'
        }
        response = requests.post(settings.GOOGLE_TOKEN_URL, data=data, timeout=10)
        if response.status_code != 200:
            raise GoogleAPIError("Failed to obtain access token from Google")
        return response.json().get('access_token')

    def get_google_user_info(self, access_token):
        headers = {'Authorization': f'Bearer {access_token}'}
        response = requests.get(settings.GOOGLE_USER_INFO_URL, headers=headers, timeout=10)
        if response.status_code != 200:
            raise GoogleAPIError("Failed to get user info from Google")
        return response.json()

    @transaction.atomic
    def get_or_create_user(self, google_user):
        email = google_user.get('email')
        if not email:
            raise UserCreationError("Email is required")

        try:
            user = User.objects.get(email=email)
            user.last_login = timezone.now()
            user.save(update_fields=['last_login'])
        except User.DoesNotExist:
            try:
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    first_name=google_user.get('given_name', ''),
                    last_name=google_user.get('family_name', ''),
                    social_id=f"google_{google_user.get('id')}",
                    social_type='google'
                )
            except ValidationError as e:
                raise UserCreationError(str(e))

        return user

    def get_tokens_for_user(self, user):
        refresh = RefreshToken.for_user(user)
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }
        
class Enable2FAView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_summary="2차인증 활성화",
        operation_description="Enable 2FA for the authenticated user",
        tags=['User'],
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={}
        ),
        responses={
            200: openapi.Response(
                description="2FA enabled successfully",
                examples={
                    "application/json": {
                        "status": "success",
                        "message": "2FA has been enabled. Use the QR code to set up your authenticator app.",
                        "data": {"otp_secret": "BASE32SECRET", "qr_code": "base64_image_string"}
                    }
                }
            ),
            400: openapi.Response(description="Bad Request"),
            401: openapi.Response(description="Unauthorized"),
            500: openapi.Response(description="Internal Server Error")
        }
    )
    def post(self, request, *args, **kwargs):
        user = request.user
        if user.is_2fa_enabled:
            return Response({
                "status": "error",
                "message": "2FA is already enabled."
            }, status=status.HTTP_400_BAD_REQUEST)

        user.otp_secret = pyotp.random_base32()
        user.is_2fa_enabled = True
        user.save()

        otpauth_url = pyotp.totp.TOTP(user.otp_secret).provisioning_uri(user.username, issuer_name="TEST 앱")
        qr = qrcode.make(otpauth_url)
        qr_io = BytesIO()
        qr.save(qr_io, 'PNG')
        qr_io.seek(0)
        
        qr_base64 = base64.b64encode(qr_io.getvalue()).decode()

        return Response({
            "status": "success",
            "message": "2FA has been enabled. Use the QR code to set up your authenticator app.",
            "data": {
                "otp_secret": user.otp_secret,
                "qr_code": qr_base64
            }
        }, status=status.HTTP_200_OK)

class Verify2FAView(APIView):
    permission_classes = [AllowAny]

    @swagger_auto_schema(
        operation_summary="2차인증 확인",
        operation_description="Verify 2FA token for the authenticated user. Provide the username and 2FA token.",
        tags=['User'],
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'username': openapi.Schema(type=openapi.TYPE_STRING, description='Username of the user'),
                'token': openapi.Schema(type=openapi.TYPE_STRING, description='2FA token'),
            },
            required=['username', 'token']
        ),
        responses={
            200: openapi.Response(
                description="2FA verification successful",
                examples={
                    "application/json": {
                        "status": "success",
                        "message": "2FA verification successful.",
                        "tokens": {
                            "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
                            "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
                        }
                    }
                }
            ),
            400: openapi.Response(description="Bad Request"),
            401: openapi.Response(description="Unauthorized"),
            500: openapi.Response(description="Internal Server Error")
        }
    )
    def post(self, request, *args, **kwargs):
        serializer = Verify2FASerializer(data=request.data)
        if serializer.is_valid():
            username = serializer.validated_data['username']
            token = serializer.validated_data['token']
            try:
                user = User.objects.get(username=username)
                if not user.is_2fa_enabled:
                    return Response({
                        "status": "error",
                        "message": "2FA is not enabled for this user."
                    }, status=status.HTTP_400_BAD_REQUEST)

                totp = pyotp.TOTP(user.otp_secret)
                if totp.verify(token):
                    refresh = RefreshToken.for_user(user)
                    return Response({
                        "status": "success",
                        "message": "2FA verification successful.",
                        "tokens": {
                            'refresh': str(refresh),
                            'access': str(refresh.access_token),
                        }
                    }, status=status.HTTP_200_OK)
                else:
                    return Response({
                        "status": "error",
                        "message": "Invalid 2FA token."
                    }, status=status.HTTP_400_BAD_REQUEST)
            except User.DoesNotExist:
                return Response({
                    "status": "error",
                    "message": "User not found."
                }, status=status.HTTP_404_NOT_FOUND)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class Disable2FAView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_summary="2차인증 비활성화",
        operation_description="Disable 2FA for the authenticated user",
        tags=['User'],
        responses={
            200: openapi.Response(
                description="2FA disabled successfully",
                examples={
                    "application/json": {
                        "status": "success",
                        "message": "2FA has been disabled."
                    }
                }
            ),
            400: openapi.Response(description="Bad Request"),
            401: openapi.Response(description="Unauthorized"),
            500: openapi.Response(description="Internal Server Error")
        }
    )
    def post(self, request, *args, **kwargs):
        user = request.user
        if not user.is_2fa_enabled:
            return Response({
                "status": "error",
                "message": "2FA is not enabled."
            }, status=status.HTTP_400_BAD_REQUEST)

        user.is_2fa_enabled = False
        user.otp_secret = None
        user.save()

        return Response({
            "status": "success",
            "message": "2FA has been disabled."
        }, status=status.HTTP_200_OK)

class AccountSecurityView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_summary="계정 보안 정보 조회",
        operation_description="사용자의 보안 설정 및 최근 로그인 기록을 조회합니다.",
        tags=['User'],
        responses={
            200: openapi.Response(
                description="성공적인 응답",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'security_settings': openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            properties={
                                'is_2fa_enabled': openapi.Schema(type=openapi.TYPE_BOOLEAN, description="2단계 인증 활성화 여부"),
                                'last_password_change': openapi.Schema(type=openapi.TYPE_STRING, format=openapi.FORMAT_DATETIME, description="마지막 비밀번호 변경 시간"),
                                'is_locked': openapi.Schema(type=openapi.TYPE_BOOLEAN, description="계정 잠금 여부"),
                                'failed_login_attempts': openapi.Schema(type=openapi.TYPE_INTEGER, description="실패한 로그인 시도 횟수"),
                            }
                        ),
                        'login_history': openapi.Schema(
                            type=openapi.TYPE_ARRAY,
                            items=openapi.Schema(
                                type=openapi.TYPE_OBJECT,
                                properties={
                                    'login_time': openapi.Schema(type=openapi.TYPE_STRING, format=openapi.FORMAT_DATETIME, description="로그인 시간"),
                                    'ip_address': openapi.Schema(type=openapi.TYPE_STRING, description="IP 주소"),
                                    'user_agent': openapi.Schema(type=openapi.TYPE_STRING, description="사용자 에이전트"),
                                    'success': openapi.Schema(type=openapi.TYPE_BOOLEAN, description="로그인 성공 여부"),
                                    'location': openapi.Schema(type=openapi.TYPE_STRING, description="로그인 위치"),
                                }
                            )
                        ),
                    }
                )
            ),
            401: openapi.Response(description="인증되지 않은 사용자")
        }
    )
    def get(self, request):
        user = request.user
        login_history = LoginHistory.objects.filter(user=user).order_by('-login_time')[:5]

        user_serializer = CustomUserSerializer(user)
        history_serializer = LoginHistorySerializer(login_history, many=True)

        return Response({
            'security_settings': {
                'is_2fa_enabled': user.is_2fa_enabled,
                'last_password_change': user.last_password_change,
                'is_locked': user.is_locked,
                'failed_login_attempts': user.failed_login_attempts,
            },
            'login_history': history_serializer.data
        })

    @swagger_auto_schema(
        operation_summary="계정 보안 설정 업데이트",
        operation_description="사용자의 보안 설정을 업데이트합니다.",
        tags=['User'],
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'is_2fa_enabled': openapi.Schema(type=openapi.TYPE_BOOLEAN, description="2단계 인증 활성화 여부"),
            },
            required=['is_2fa_enabled']
        ),
        responses={
            200: openapi.Response(
                description="성공적인 업데이트",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'is_2fa_enabled': openapi.Schema(type=openapi.TYPE_BOOLEAN, description="업데이트된 2단계 인증 상태"),
                        'message': openapi.Schema(type=openapi.TYPE_STRING, description="성공 메시지"),
                    }
                )
            ),
            400: openapi.Response(description="잘못된 요청"),
            401: openapi.Response(description="인증되지 않은 사용자")
        }
    )
    def post(self, request):
        user = request.user
        is_2fa_enabled = request.data.get('is_2fa_enabled')

        if is_2fa_enabled is not None:
            user.is_2fa_enabled = is_2fa_enabled
            user.save()
            return Response({
                'is_2fa_enabled': user.is_2fa_enabled,
                'message': '2단계 인증 설정이 성공적으로 업데이트되었습니다.'
            })
        return Response({'error': '유효하지 않은 데이터'}, status=status.HTTP_400_BAD_REQUEST)