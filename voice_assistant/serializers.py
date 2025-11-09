from __future__ import annotations

from typing import Any, Dict

from rest_framework import serializers

from .models import VoiceInteraction, VoiceSession


class VoiceSessionCreateSerializer(serializers.Serializer):
    voice = serializers.CharField(required=False, allow_blank=True)
    instructions = serializers.CharField(required=False, allow_blank=True)
    modalities = serializers.ListField(
        child=serializers.ChoiceField(choices=("audio", "text")),
        required=False,
        allow_empty=True,
    )
    metadata = serializers.DictField(required=False, child=serializers.CharField(), allow_empty=True)
    device = serializers.DictField(required=False)
    turn_detection = serializers.DictField(required=False)

    def validate_modalities(self, value: list[str]) -> list[str]:
        if not value:
            return ["audio", "text"]
        if "audio" not in value:
            raise serializers.ValidationError("실시간 음성 대화에는 audio modality가 반드시 포함되어야 합니다.")
        return value

    def validate_metadata(self, value: Dict[str, Any]) -> Dict[str, Any]:
        # 기본적으로 dict를 기대하며, nested 구조를 허용
        return value or {}

    def create(self, validated_data: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("VoiceSessionCreateSerializer는 create를 지원하지 않습니다.")

    def update(self, instance: Any, validated_data: Dict[str, Any]) -> Any:
        raise NotImplementedError("VoiceSessionCreateSerializer는 update를 지원하지 않습니다.")


class VoiceSessionListSerializer(serializers.ModelSerializer):
    is_expired = serializers.SerializerMethodField()

    class Meta:
        model = VoiceSession
        fields = (
            "id",
            "openai_session_id",
            "model",
            "voice",
            "modalities",
            "instructions",
            "metadata",
            "webrtc_url",
            "status",
            "client_secret_expires_at",
            "is_expired",
            "created_at",
            "updated_at",
        )

    def get_is_expired(self, obj: VoiceSession) -> bool:
        return obj.is_expired()


class VoiceSessionCreateResponseSerializer(VoiceSessionListSerializer):
    client_secret = serializers.SerializerMethodField()

    class Meta(VoiceSessionListSerializer.Meta):
        fields = VoiceSessionListSerializer.Meta.fields + ("client_secret",)

    def get_client_secret(self, obj: VoiceSession) -> Dict[str, Any]:
        """
        세션 생성 직후에만 클라이언트에 에페메랄 토큰을 전달합니다.
        """
        del obj
        secret = self.context.get("client_secret")
        if not secret:
            return {}
        return {
            "value": secret.get("value"),
            "expires_at": secret.get("expires_at"),
        }


class VoiceInteractionSerializer(serializers.ModelSerializer):
    class Meta:
        model = VoiceInteraction
        fields = ("id", "role", "content", "audio_url", "payload", "created_at")


class VoiceInteractionCreateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=VoiceInteraction.InteractionRole.choices)
    content = serializers.CharField(required=False, allow_blank=True)
    audio_url = serializers.URLField(required=False, allow_blank=True)
    payload = serializers.DictField(required=False)

    def create(self, validated_data: Dict[str, Any]) -> VoiceInteraction:
        session: VoiceSession = self.context["session"]
        return VoiceInteraction.objects.create(session=session, **validated_data)

    def update(self, instance: VoiceInteraction, validated_data: Dict[str, Any]) -> VoiceInteraction:
        raise NotImplementedError("VoiceInteractionCreateSerializer는 update를 지원하지 않습니다.")


