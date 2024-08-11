from django.contrib.auth.models import AbstractUser
from django.db import models
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
import uuid

class CustomUser(AbstractUser):
    unique_id = models.UUIDField(default=uuid.uuid4, unique=True)
    email = models.EmailField(unique=True, blank=False)
    phone_number = models.CharField(max_length=11, blank=False)
    service_agreement = models.BooleanField(default=False)
    privacy_agreement = models.BooleanField(default=False)
    promotion_agreement = models.BooleanField(default=False, blank=True)
    social_type = models.CharField(max_length=20, blank=True, null=True)
    social_id = models.CharField(max_length=100, blank=True, null=True)
    is_locked = models.BooleanField(default=False)
    failed_login_attempts = models.IntegerField(default=0)
    last_password_change = models.DateTimeField(default=timezone.now)
    security_question = models.CharField(max_length=255, blank=True)
    security_answer = models.CharField(max_length=255, blank=True)
    is_2fa_enabled = models.BooleanField(default=False)
    otp_secret = models.CharField(max_length=16, blank=True, null=True)
    preferred_speaking_style = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return self.username

class LoginHistory(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    login_time = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    success = models.BooleanField()
    location = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.login_time}"

class EmailVerification(models.Model):
    user = models.OneToOneField(get_user_model(), on_delete=models.CASCADE)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Verification for {self.user.username}"