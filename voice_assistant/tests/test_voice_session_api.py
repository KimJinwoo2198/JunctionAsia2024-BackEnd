from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from voice_assistant.models import VoiceSession


class VoiceSessionAPITestCase(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="voice-user",
            email="voice@example.com",
            password="StrongPass!23",
        )
        self.url = reverse("voice_assistant:voice-session-list")

    def authenticate(self):
        self.client.force_authenticate(user=self.user)

    def test_create_voice_session_requires_auth(self):
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("voice_assistant.views.OpenAIRealtimeService.create_session")
    def test_create_voice_session_success(self, mock_create_session):
        self.authenticate()

        expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)
        mock_create_session.return_value = {
            "id": "sess_123",
            "voice": "alloy",
            "modalities": ["audio", "text"],
            "webrtc": {"url": "wss://example.com"},
            "client_secret": {
                "value": "ephemeral-token-value",
                "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
            },
        }

        payload = {
            "metadata": {"client": "ios"},
            "instructions": "테스트 모드 지시문",
        }
        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("client_secret", response.data)
        self.assertEqual(response.data["voice"], "alloy")
        self.assertEqual(response.data["modalities"], ["audio", "text"])
        self.assertEqual(response.data["status"], VoiceSession.SessionStatus.CREATED)
        self.assertTrue(VoiceSession.objects.filter(user=self.user).exists())  # type: ignore[attr-defined]

    @patch("voice_assistant.views.OpenAIRealtimeService.create_session")
    def test_list_voice_sessions(self, mock_create_session):
        self.authenticate()

        expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)
        mock_create_session.return_value = {
            "id": "sess_list",
            "voice": "verse",
            "modalities": ["audio", "text"],
            "webrtc": {"url": "wss://example.com"},
            "client_secret": {
                "value": "token-value",
                "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
            },
        }

        self.client.post(self.url, {}, format="json")

        list_response = self.client.get(self.url)
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(list_response.data), 1)
        self.assertEqual(list_response.data[0]["openai_session_id"], "sess_list")


