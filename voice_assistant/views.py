from __future__ import annotations

import logging
from typing import Any, Dict

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_yasg.utils import swagger_auto_schema

from .exceptions import OpenAIRealtimeException
from .models import VoiceSession
from .serializers import (
    VoiceInteractionCreateSerializer,
    VoiceInteractionSerializer,
    VoiceSessionCreateResponseSerializer,
    VoiceSessionCreateSerializer,
    VoiceSessionListSerializer,
)
from .services import OpenAIRealtimeService

logger = logging.getLogger(__name__)


def _build_default_instructions(user, custom_instructions: str | None = None) -> str:
    base_instruction = getattr(settings, "VOICE_ASSISTANT_PROMPT", "")
    style = getattr(user, "preferred_speaking_style", None)

    parts = [
        base_instruction.strip(),
        f"사용자의 선호 화법: {style}" if style else "",
        custom_instructions.strip() if custom_instructions else "",
    ]
    return "\n".join(filter(None, parts))


class VoiceSessionListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_summary="실시간 음성 세션 발급",
        operation_description="OpenAI Realtime API를 통해 음성 대화 세션을 생성하고 에페메랄 토큰을 발급합니다.",
        request_body=VoiceSessionCreateSerializer,
        responses={
            201: VoiceSessionCreateResponseSerializer,
            400: "잘못된 요청",
            500: "서버 오류",
        },
        tags=["Voice"],
    )
    def post(self, request):
        serializer = VoiceSessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        config = getattr(settings, "VOICE_ASSISTANT_CONFIG", {})
        model = validated.get("model") or config.get("model", "gpt-4o-realtime-preview-2024-12-17")
        voice = validated.get("voice") or config.get("default_voice", "alloy")
        modalities = validated.get("modalities") or config.get("default_modalities", ["audio", "text"])

        instructions = _build_default_instructions(request.user, validated.get("instructions"))
        metadata: Dict[str, Any] = {
            "user_id": str(request.user.unique_id) if hasattr(request.user, "unique_id") else request.user.pk,
            "username": request.user.username,
            "session_origin": "web",
        }
        metadata.update(validated.get("metadata", {}))

        service = OpenAIRealtimeService()
        try:
            session_payload = service.create_session(
                model=model,
                voice=voice,
                modalities=modalities,
                instructions=instructions,
                metadata=metadata,
                turn_detection=validated.get("turn_detection")
                or config.get(
                    "turn_detection",
                    {"type": "voice_activity_detection", "threshold": 0.6, "silence_duration_ms": 600},
                ),
            )
        except OpenAIRealtimeException as exc:
            logger.exception("OpenAI 실시간 세션 생성 실패: %s", exc)
            return Response(
                {
                    "message": "실시간 세션 생성에 실패했습니다.",
                    "detail": str(exc),
                    "upstream_status": exc.status_code,
                    "upstream_payload": exc.payload,
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        client_secret = session_payload.get("client_secret", {})
        expires_at = OpenAIRealtimeService.parse_expires_at(client_secret.get("expires_at"))

        webrtc_info = session_payload.get("webrtc") or {}
        webrtc_url = (
            webrtc_info.get("url")
            or session_payload.get("webrtc_url")
            or service.build_webrtc_url(model)
        )

        if not webrtc_url:
            logger.error("OpenAI Realtime 응답에 webrtc_url이 없습니다: %s", session_payload)
            return Response(
                {
                    "message": "실시간 세션 생성에 실패했습니다.",
                    "detail": "OpenAI 응답에 WebRTC URL이 포함되지 않았습니다.",
                    "upstream_payload": session_payload,
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        voice_session = VoiceSession.objects.create(
            user=request.user,
            openai_session_id=session_payload.get("id", ""),
            model=model,
            voice=session_payload.get("voice", voice),
            modalities=session_payload.get("modalities") or modalities,
            instructions=instructions,
            metadata=metadata,
            webrtc_url=webrtc_url,
            client_secret_hash=VoiceSession.hash_client_secret(client_secret.get("value", "")),
            client_secret_last4=VoiceSession.last4(client_secret.get("value", "")),
            client_secret_expires_at=expires_at,
            status=VoiceSession.SessionStatus.CREATED,
        )

        response_serializer = VoiceSessionCreateResponseSerializer(
            voice_session,
            context={
                "client_secret": {
                    "value": client_secret.get("value"),
                    "expires_at": expires_at.isoformat(),
                }
            },
        )
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @swagger_auto_schema(
        operation_summary="나의 음성 세션 목록",
        responses={200: VoiceSessionListSerializer(many=True)},
        tags=["Voice"],
    )
    def get(self, request):
        queryset = VoiceSession.objects.filter(user=request.user).order_by("-created_at")[:50]

        # 만료 처리 업데이트
        for session in queryset:
            if session.is_expired() and session.status not in {
                VoiceSession.SessionStatus.EXPIRED,
                VoiceSession.SessionStatus.ENDED,
            }:
                session.mark_expired()

        serializer = VoiceSessionListSerializer(queryset, many=True)
        return Response(serializer.data)


class VoiceSessionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_summary="세션 상세 조회",
        responses={200: VoiceSessionListSerializer},
        tags=["Voice"],
    )
    def get(self, request, session_id):
        session = get_object_or_404(VoiceSession, id=session_id, user=request.user)
        if session.is_expired() and session.status not in {
            VoiceSession.SessionStatus.EXPIRED,
            VoiceSession.SessionStatus.ENDED,
        }:
            session.mark_expired()
        serializer = VoiceSessionListSerializer(session)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary="세션 종료",
        responses={204: "종료됨"},
        tags=["Voice"],
    )
    def delete(self, request, session_id):
        session = get_object_or_404(VoiceSession, id=session_id, user=request.user)
        session.mark_ended()
        return Response(status=status.HTTP_204_NO_CONTENT)


class VoiceInteractionView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_summary="세션 인터랙션 로그 조회",
        responses={200: VoiceInteractionSerializer(many=True)},
        tags=["Voice"],
    )
    def get(self, request, session_id):
        session = get_object_or_404(VoiceSession, id=session_id, user=request.user)
        interactions = session.interactions.all()
        serializer = VoiceInteractionSerializer(interactions, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary="세션 인터랙션 로그 추가",
        request_body=VoiceInteractionCreateSerializer,
        responses={201: VoiceInteractionSerializer},
        tags=["Voice"],
    )
    def post(self, request, session_id):
        session = get_object_or_404(VoiceSession, id=session_id, user=request.user)
        serializer = VoiceInteractionCreateSerializer(
            data=request.data,
            context={"session": session},
        )
        serializer.is_valid(raise_exception=True)
        interaction = serializer.save()
        output_serializer = VoiceInteractionSerializer(interaction)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)


