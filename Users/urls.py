from rest_framework.authtoken.views import obtain_auth_token
from django.urls import path, include
from .views import ( 
    SignupView, 
    LoginView, 
    PasswordChangeView, 
    UnlockAccountView, 
    GoogleLoginView, 
    GoogleCallbackView, 
    LogoutView, 
    Enable2FAView, 
    Verify2FAView, 
    Disable2FAView,
    AccountSecurityView
)


urlpatterns = [
    path('signup/', SignupView.as_view(), name='api_signup'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='api_logout'),
    path('password_change/', PasswordChangeView.as_view(), name='password_change'),
    path('unlock_account/', UnlockAccountView.as_view(), name='unlock_account'),
    path('login/google/', GoogleLoginView.as_view(), name='google_login'),
    path('oauth/google/login/callback/', GoogleCallbackView.as_view(), name='google_callback'),
    path('enable-2fa/', Enable2FAView.as_view(), name='enable-2fa'),
    path('verify-2fa/', Verify2FAView.as_view(), name='verify-2fa'),
    path('disable-2fa/', Disable2FAView.as_view(), name='disable-2fa'),
    path('account/security/', AccountSecurityView.as_view(), name='account_security'),
]
