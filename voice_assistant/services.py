from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

import httpx
from django.conf import settings

from .exceptions import OpenAIRealtimeException

logger = logging.getLogger(__name__)


class OpenAIRealtimeService:
    """
    OpenAI Realtime API와 통신하는 서비스 레이어.

    - 세션 생성은 서버에서 수행하여 클라이언트에 에페메랄 토큰을 전달합니다.
    - HTTP 타임아웃, 재시도 정책, 로깅을 표준화합니다.
    """

    OPENAI_BETA_HEADER = "realtime=v1"

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        self.api_key = api_key or getattr(settings, "OPENAI_API_KEY", "")
        self.api_base = api_base or getattr(settings, "OPENAI_API_BASE", "https://api.openai.com/v1")
        self.timeout = timeout

        if not self.api_key:
            raise OpenAIRealtimeException("OPENAI_API_KEY가 설정되어 있지 않습니다.")

    def build_webrtc_url(self, model: str) -> str:
        """
        WebRTC SDP 교환에 사용할 기본 URL을 반환합니다.
        OpenAI 문서 기준으로 https POST 엔드포인트를 사용합니다.
        """
        base = self.api_base.rstrip("/")
        # 대부분의 경우 api_base는 https://api.openai.com/v1 형태
        return f"{base}/realtime?model={model}"

    def create_session(
        self,
        *,
        model: str,
        voice: str,
        modalities: Iterable[str],
        instructions: str,
        metadata: dict,
        turn_detection: Optional[dict] = None,
        **additional_payload: Any,
    ) -> Dict[str, Any]:
        """
        OpenAI Realtime 세션을 생성하고 응답 payload를 반환합니다.
        """
        payload: Dict[str, Any] = {
            "model": model,
            "voice": voice,
            "modalities": list(modalities),
            "instructions": instructions,
        }

        if turn_detection:
            payload["turn_detection"] = turn_detection

        if additional_payload:
            payload.update(additional_payload)

        if metadata:
            logger.debug(
                "메타데이터는 OpenAI Realtime 세션 생성 요청에 포함되지 않습니다.",
                extra={"metadata_keys": list(metadata.keys())},
            )

        logger.info("OpenAI Realtime 세션 생성 시작", extra={"voice": voice, "modalities": payload["modalities"]})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "OpenAI-Beta": self.OPENAI_BETA_HEADER,
        }

        url = f"{self.api_base.rstrip('/')}/realtime/sessions"

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, headers=headers, json=payload)
        except httpx.RequestError as exc:
            logger.exception("OpenAI Realtime 세션 생성 중 네트워크 오류: %s", exc)
            raise OpenAIRealtimeException("OpenAI Realtime API와 통신에 실패했습니다.") from exc

        if response.status_code >= 400:
            self._log_and_raise_http_error(response)

        data = response.json()
        logger.debug("OpenAI Realtime 세션 생성 응답: %s", data)
        return data

    @staticmethod
    def parse_expires_at(value: Any) -> datetime:
        """
        OpenAI 응답의 expires_at 필드를 datetime으로 파싱합니다.
        """
        if value is None:
            raise OpenAIRealtimeException("OpenAI 응답에 expires_at 정보가 없습니다.")

        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)

        if isinstance(value, str):
            # 2024-10-01T00:00:00Z 형식을 지원
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            return datetime.fromisoformat(value)

        raise OpenAIRealtimeException("알 수 없는 expires_at 포맷입니다.")

    @staticmethod
    def _log_and_raise_http_error(response: httpx.Response) -> None:
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}

        logger.error(
            "OpenAI Realtime API 호출 실패",
            extra={"status_code": response.status_code, "payload": payload},
        )
        raise OpenAIRealtimeException(
            "OpenAI Realtime API 호출이 실패했습니다.",
            status_code=response.status_code,
            payload=payload,
        )


