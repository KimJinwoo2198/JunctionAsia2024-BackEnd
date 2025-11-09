import hashlib
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from django.conf import settings
from django.db import models
from django.utils import timezone


class VoiceSession(models.Model):
    class SessionStatus(models.TextChoices):
        CREATED = "created", "생성됨"
        ACTIVE = "active", "진행중"
        ENDED = "ended", "종료됨"
        EXPIRED = "expired", "만료됨"
        FAILED = "failed", "실패"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="voice_sessions",
        on_delete=models.CASCADE,
    )
    openai_session_id = models.CharField(max_length=128)
    model = models.CharField(max_length=64)
    voice = models.CharField(max_length=64)
    modalities = models.JSONField(default=list, blank=True)
    instructions = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    webrtc_url = models.URLField(max_length=512, blank=True)

    client_secret_hash = models.CharField(max_length=64)
    client_secret_last4 = models.CharField(max_length=4)
    client_secret_expires_at = models.DateTimeField()

    status = models.CharField(
        max_length=16,
        choices=SessionStatus.choices,
        default=SessionStatus.CREATED,
    )
    error_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = models.Manager()

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["openai_session_id"]),
        ]

    @staticmethod
    def hash_client_secret(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def last4(value: str) -> str:
        return value[-4:] if len(value) >= 4 else value

    def mark_expired(self) -> None:
        if self.status not in {
            self.SessionStatus.EXPIRED,
            self.SessionStatus.ENDED,
            self.SessionStatus.FAILED,
        }:
            self.status = self.SessionStatus.EXPIRED
            self.save(update_fields=["status", "updated_at"])

    def mark_ended(self) -> None:
        if self.status not in {
            self.SessionStatus.ENDED,
            self.SessionStatus.FAILED,
        }:
            self.status = self.SessionStatus.ENDED
            self.save(update_fields=["status", "updated_at"])

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        now = now or timezone.now()
        return now >= self.client_secret_expires_at

    def set_failure(self, message: str) -> None:
        self.status = self.SessionStatus.FAILED
        self.error_message = message[:2048]
        self.save(update_fields=["status", "error_message", "updated_at"])


class VoiceInteraction(models.Model):
    class InteractionRole(models.TextChoices):
        USER = "user", "사용자"
        ASSISTANT = "assistant", "어시스턴트"
        SYSTEM = "system", "시스템"

    session = models.ForeignKey(
        VoiceSession,
        related_name="interactions",
        on_delete=models.CASCADE,
    )
    role = models.CharField(max_length=16, choices=InteractionRole.choices)
    content = models.TextField(blank=True)
    audio_url = models.URLField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = models.Manager()

    class Meta:
        ordering = ("created_at",)
        indexes = [
            models.Index(fields=["session", "created_at"]),
            models.Index(fields=["role"]),
        ]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "audio_url": self.audio_url,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
        }


