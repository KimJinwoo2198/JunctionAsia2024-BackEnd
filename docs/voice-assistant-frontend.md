# 실시간 음성 어시스턴트 프런트엔드 연동 가이드

본 문서는 `voice_assistant` 백엔드 모듈을 기반으로 웹/모바일 클라이언트에서 OpenAI Realtime 음성 대화를 연동하는 절차를 설명합니다. Django API 서버는 JWT 인증 기반으로 세션 발급과 로그 적재를 담당하며, 브라우저/앱은 WebRTC를 통해 OpenAI Realtime 엔드포인트와 직접 통신합니다.

---

## 1. 아키텍처 개요

- **클라이언트**  
  - 사용자 JWT를 포함해 백엔드에 세션 발급 요청  
  - 응답으로 받는 `client_secret`과 `webrtc.url`을 이용해 WebRTC PeerConnection 구성  
  - 마이크 스트림을 업로드하고 OpenAI가 반환하는 오디오 트랙을 수신  
  - 필요 시 인터랙션 로그를 백엔드로 전송  

- **백엔드 (`voice_assistant` 앱)**  
  - `POST /api/voice/sessions/`에서 OpenAI Realtime 세션 생성 및 에페메랄 키 발급  
  - 세션/인터랙션 메타데이터 영속화  
  - `GET /api/voice/sessions/` 등으로 세션 상태 조회  

- **OpenAI Realtime API**  
  - WebRTC 연결을 통해 양방향 음성/텍스트 대화 처리  

---

## 2. 필수 전제 조건

1. 사용자는 `JWT Access Token`을 이미 보유하고 있어야 합니다. (예: `Authorization: Bearer <token>` 헤더)
2. 프런트엔드 런타임은 WebRTC와 마이크 권한을 사용할 수 있어야 합니다. (Chrome ≥ 120, Safari ≥ 17.4 등 최신 브라우저 권장)
3. 백엔드 `.env`에 `OPENAI_API_KEY`, `VOICE_ASSISTANT_*` 환경 변수가 설정되어 있어야 합니다.

---

## 3. 세션 발급 요청 흐름

### 3.1 엔드포인트 요약

| Method | Path | 설명 |
| ------ | ---- | ---- |
| `POST` | `/api/voice/sessions/` | 실시간 세션 생성 및 에페메랄 키 발급 |
| `GET` | `/api/voice/sessions/` | 나의 세션 목록 조회 |
| `GET` | `/api/voice/sessions/:id/` | 특정 세션 상세 조회 |
| `DELETE` | `/api/voice/sessions/:id/` | 세션 종료 |
| `GET` | `/api/voice/sessions/:id/interactions/` | 인터랙션 로그 조회 |
| `POST` | `/api/voice/sessions/:id/interactions/` | 인터랙션 로그 수동 적재 (선택) |

### 3.2 세션 생성 요청 예시

```typescript
async function createVoiceSession(accessToken: string) {
  const response = await fetch("https://<api-host>/api/voice/sessions/", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({
      metadata: {
        client: "web",
        clientVersion: "1.0.0",
      },
      instructions: "필요 시 세션별 커스텀 지시문 입력",
    }),
  });

  if (!response.ok) {
    throw new Error(`세션 생성 실패: ${response.status}`);
  }

  const data = await response.json();
  return {
    sessionId: data.id,
    webrtcUrl: data.webrtc_url,
    clientSecret: data.client_secret.value,
    clientSecretExpiresAt: data.client_secret.expires_at,
  };
}
```

응답 예시 (`201 Created`):

```json
{
  "id": "6b06eb17-e2fb-4a91-8022-40105263f233",
  "openai_session_id": "sess_abc123",
  "voice": "alloy",
  "modalities": ["audio", "text"],
  "webrtc_url": "https://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-12-17",
  "client_secret": {
    "value": "ephemeral-client-secret",
    "expires_at": "2025-11-09T00:00:00Z"
  },
  "status": "created",
  "created_at": "2025-11-09T09:00:00.000000Z"
}
```

---

## 4. WebRTC 연결 절차

### 4.1 PeerConnection 초기화

```typescript
const pc = new RTCPeerConnection({
  iceServers: [
    { urls: "stun:stun.l.google.com:19302" },
  ],
});

// OpenAI에서 전달되는 오디오 트랙 수신
pc.ontrack = (event) => {
  const [remoteStream] = event.streams;
  const audioElement = document.getElementById("assistant-audio") as HTMLAudioElement;
  audioElement.srcObject = remoteStream;
  audioElement.play().catch(console.error);
};
```

### 4.2 마이크 스트림 추가

```typescript
const localStream = await navigator.mediaDevices.getUserMedia({ audio: true });
localStream.getTracks().forEach((track) => pc.addTrack(track, localStream));
```

### 4.3 SDP 교환

OpenAI Realtime WebRTC는 `client_secret`을 Bearer 토큰으로 사용합니다.

```typescript
async function connectToRealtime(webrtcUrl: string, clientSecret: string) {
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);

  const baseUrl = webrtcUrl; // 백엔드 응답의 webrtc_url
  const response = await fetch(baseUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/sdp",
      Authorization: `Bearer ${clientSecret}`,
    },
    body: offer.sdp ?? "",
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  const answerSdp = await response.text();
  await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });
}
```

> **중요**  
> - `client_secret`은 한 번만 사용 가능한 에페메랄 키입니다. 노출되면 즉시 재발급해야 합니다.
> - `client_secret_expires_at` 이내에 연결을 완료해야 합니다. 만료 후에는 `POST /api/voice/sessions/`로 새 세션을 생성해야 합니다.

### 4.4 오디오 재생 UI 예시

```html
<audio id="assistant-audio" autoplay playsinline></audio>
```

---

## 5. 대화 흐름 관리

1. 세션 연결 성공 후 사용자가 말을 시작하면 자동으로 음성 인식 및 답변이 수행됩니다.  
2. 텍스트 자막이 필요하면 WebRTC DataChannel을 추가하거나 OpenAI Realtime의 `modalities: ["audio", "text"]`를 활용하여 텍스트 응답을 수신할 수 있습니다. (추가 파싱 로직 필요)  
3. 세션 종료 시 `DELETE /api/voice/sessions/{sessionId}/` 호출로 상태를 `ended`로 변경합니다.  
4. 기록 보존이 필요하면 대화 내용을 `POST /api/voice/sessions/{sessionId}/interactions/`로 저장하거나, 백엔드에서 별도로 RAG 파이프라인에 적재할 수 있습니다.

---

## 6. 에러 처리 및 재시도 전략

- **401/403**: 사용자 토큰 만료. 로그인 갱신 후 재시도.  
- **502 (세션 생성 실패)**: 백엔드 로그 확인. OpenAI API 오류 메시지가 `upstream_payload`에 포함됩니다.  
- **WebRTC 연결 실패**: ICE 실패, 마이크 권한, 네트워크 정책 (기업 사설망 등)을 점검합니다.  
- **`client_secret` 만료**: 새 세션 생성 필요.

---

## 7. 보안 가이드라인

- `client_secret`은 네트워크 탭/로그에 남지 않도록 주의합니다. (HTTPS 필수)  
- 브라우저에 장기 저장하지 말고, 연결 완료 후 즉시 메모리에서 파기합니다.  
- JWT 토큰은 `Authorization` 헤더로만 사용하고, 로컬스토리지 대신 메모리/쿠키의 `HttpOnly` 옵션을 권장합니다.

---

## 8. QA 체크리스트

1. 마이크 권한이 거부된 경우 사용자에게 명확히 안내되는가?  
2. 세션 연결 지연(>5초) 시 로딩 상태와 재시도 UI가 제공되는가?  
3. 비정상 종료 후 `DELETE /api/voice/sessions/{id}/`를 호출해 백엔드 상태가 일관되게 유지되는가?  
4. 모바일 브라우저에서 백그라운드 전환 시 스트림이 적절히 일시 중지되는가?

---

## 9. 추가 참고

- OpenAI 공식 Realtime WebRTC 문서: https://platform.openai.com/docs/guides/realtime  
- 기본 음성 VAD 설정은 `VOICE_TURN_DETECTION_TYPE` 환경 변수(기본 `server_vad`)로 제어합니다. 필요 시 `semantic_vad`로 전환하고, 추가 옵션은 OpenAI 문서를 참고하세요.  
- `voice_assistant` Django 모델/뷰 참고:  
  - `voice_assistant/views.py` – 세션 발급 및 로그 API  
  - `voice_assistant/models.py` – 세션/인터랙션 스키마  
  - `env.example` – 필수 환경 변수 템플릿  

---

### 문의

프런트엔드 연동 중 발생하는 질문은 플랫폼 백엔드 팀(#voice-assistant)으로 문의 바랍니다. PR 제출 시에는 다음 항목을 포함하세요.

- 브라우저/OS 테스트 매트릭스  
- 마이크 권한 UX 시나리오  
- 실패/재시도 시뮬레이션 결과  
- API 호출 로그 (민감정보 마스킹)


