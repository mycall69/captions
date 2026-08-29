# SSE 이벤트 스키마: Dual Subtitle MVP

**Endpoint**: `GET /v1/jobs/{job_id}/events`

**Media Type**: `text/event-stream`

**관련**: [openapi.yaml](./openapi.yaml) · [plan.md](../plan.md) · [data-model.md](../data-model.md)

본 문서는 작업 진행 상황을 실시간으로 클라이언트에 전달하기 위한 Server-Sent Events
프로토콜을 정의한다. SSE는 한 방향 push에 적합하며 브라우저 native 지원 + 자동 재연결을
활용한다.

## 공통 규칙

- 모든 이벤트는 `event:` 필드(타입)와 `data:` 필드(JSON payload)를 가진다.
- `id:` 필드는 monotonic increasing 정수(`job_event.id` ORM PK)를 사용한다.
- 클라이언트는 재연결 시 `Last-Event-ID` 헤더를 자동 전송 — 서버는 해당 id 이후의
  이벤트만 replay한 뒤 라이브 스트림에 합류시킨다(replay 한도 50건).
- payload의 모든 timestamp는 ISO-8601 UTC.
- payload 메시지(`message` 필드)는 한국어로 작성한다 (헌법 V).
- 연결이 30초 이상 idle하면 서버가 SSE `comment` (`: keepalive\n\n`)를 push한다.

## 이벤트 타입

### `job.state_changed`

작업 상태가 새 단계로 전이될 때 1회 발행.

```
event: job.state_changed
id: 142
data: {
  "job_id": "01HX2T...",
  "previous_status": "downloading",
  "status": "subtitle_processing",
  "stage": "subtitle_processing",
  "at": "2026-05-27T09:31:22.103Z"
}
```

### `job.progress`

같은 단계 내 진행률 갱신. 단계 시작 시 `progress=0.0`, 종료 시 `progress=1.0`.

```
event: job.progress
id: 143
data: {
  "job_id": "01HX2T...",
  "status": "translating",
  "stage": "translating",
  "progress": 0.46,
  "detail": {
    "chunk_index": 12,
    "chunk_total": 26
  },
  "at": "2026-05-27T09:31:35.402Z"
}
```

- `detail`은 stage에 따라 schema가 다르다. 클라이언트는 모르는 키를 무시한다.
- 각 stage의 `detail` 키:
  - `downloading`: `{ "downloaded_bytes": int, "total_bytes": int | null }`
  - `subtitle_processing`: `{ "cue_count": int }`
  - `translating`: `{ "chunk_index": int, "chunk_total": int, "retry_count": int }`
  - `rendering`: `{ "format": "dual_srt" | "dual_vtt" }`

### `job.completed`

종결 — 성공. 클라이언트는 이 이벤트를 받으면 작업 상세 데이터를 한 번 더 fetch해
재생 가능 자산을 노출한다.

```
event: job.completed
id: 200
data: {
  "job_id": "01HX2T...",
  "status": "completed",
  "completed_at": "2026-05-27T09:38:11.001Z",
  "assets": {
    "video_mp4": "/v1/jobs/01HX2T.../video",
    "dual_srt": "/v1/jobs/01HX2T.../download?format=srt",
    "dual_vtt": "/v1/jobs/01HX2T.../download?format=vtt"
  }
}
```

### `job.failed`

종결 — 실패. `error_code` / `error_message` / `error_stage`를 포함한다.

```
event: job.failed
id: 201
data: {
  "job_id": "01HX2T...",
  "status": "failed",
  "error_stage": "subtitle_processing",
  "error_code": "SUBTITLE_NOT_FOUND",
  "error_message": "이 영상에는 한국어 / 일본어 자막이 없습니다.",
  "at": "2026-05-27T09:31:22.103Z"
}
```

### `job.info`

비차단성 알림 (자동 자막 fallback 사용 등).

```
event: job.info
id: 144
data: {
  "job_id": "01HX2T...",
  "code": "AUTO_SUBTITLE_FALLBACK",
  "message": "수동 자막이 없어 자동 자막을 사용합니다.",
  "at": "2026-05-27T09:31:24.500Z"
}
```

## 클라이언트 동작

- 연결 즉시 가장 최신 상태를 보장하기 위해 서버는 연결 직후 현재 상태에 해당하는
  `job.state_changed` 한 건을 합성해 push한다 (없는 경우 생략).
- 클라이언트는 이벤트를 받아 TanStack Query의 `setQueryData`로 작업 상세를 부분 갱신한다.
- `job.completed` / `job.failed` 수신 시 클라이언트가 명시적으로 connection을 close해도 좋다.
- 연결이 끊기면 EventSource의 기본 재연결을 따른다(초기 backoff 1s, 최대 30s).

## 백엔드 구현 메모

- 발행 채널: Redis Pub/Sub `job:{job_id}`.
- FastAPI SSE 핸들러는 `aiohttp-sse` 대신 `sse-starlette` 사용(권장).
- `job_event` 테이블은 모든 발행 이벤트를 동시 INSERT한다 — replay 정확도 보장.
- 단일 워커가 동일 이벤트를 두 번 publish하지 않도록 task 안에서 **상태 전이 + DB INSERT + publish** 를 트랜잭션으로 묶는다 (서비스 계층 패턴).
