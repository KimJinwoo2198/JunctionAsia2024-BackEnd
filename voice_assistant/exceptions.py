class OpenAIRealtimeException(Exception):
    """OpenAI 실시간 세션 생성 중 발생하는 예외."""

    def __init__(self, message: str, *, status_code: int | None = None, payload: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


class VoiceSessionNotFound(Exception):
    """세션을 찾을 수 없을 때 발생."""


class VoiceSessionOwnershipError(Exception):
    """세션이 다른 사용자에게 속해 있을 때 발생."""


