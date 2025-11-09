from django.urls import path

from .views import (
    VoiceInteractionView,
    VoiceSessionDetailView,
    VoiceSessionListCreateView,
)

app_name = "voice_assistant"

urlpatterns = [
    path("voice/sessions/", VoiceSessionListCreateView.as_view(), name="voice-session-list"),
    path("voice/sessions/<uuid:session_id>/", VoiceSessionDetailView.as_view(), name="voice-session-detail"),
    path(
        "voice/sessions/<uuid:session_id>/interactions/",
        VoiceInteractionView.as_view(),
        name="voice-session-interactions",
    ),
]


