# Data Model: Dual Subtitle MVP

**Feature**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) · **Research**: [research.md](./research.md)

**Created**: 2026-05-27

SQLite를 기본 스토어로 하며, **PostgreSQL portable schema**를 유지한다 (헌법 — SQLite-specific
SQL 금지). 미디어 / 자막 원본 파일은 파일시스템(`var/storage/<job_id>/`)에 보관하고, DB는
메타데이터 + cue 데이터만 보유한다.

## ER 개요

```
VideoJob 1───* VideoAsset
        │
        1───* SubtitleTrack 1───* SubtitleCue
        │
        1───* TranslationTask
        │
        1───* RenderTask
        │
        1───* JobEvent  (감사용)
```

## 엔티티 명세

### `video_job`

| 컬럼 | 타입 | 제약 | 비고 |
|---|---|---|---|
| `id` | UUID (TEXT, ULID 권장) | PK | 클라이언트 노출 ID |
| `source_url` | TEXT | NOT NULL | 정규화 후 저장 |
| `youtube_video_id` | TEXT | NOT NULL, INDEX | 11자 ID. 동일 URL 재요청 lookup |
| `source_language` | TEXT(2) | NULL | `ko` / `ja`. 자막 추출 완료 후 확정 |
| `target_language` | TEXT(2) | NULL | source 결정 시 자동 산정 (ko↔ja) |
| `status` | TEXT | NOT NULL | enum (아래 §상태 머신) |
| `error_stage` | TEXT | NULL | 실패 시 단계명 |
| `error_message` | TEXT | NULL | 사용자 친화 메시지 |
| `error_code` | TEXT | NULL | API 에러 코드와 동일 |
| `video_title` | TEXT | NULL | yt-dlp 메타 |
| `video_channel` | TEXT | NULL |  |
| `video_channel_url` | TEXT | NULL | YouTube 채널 페이지 URL — `channel_url`(fallback: `uploader_url`) 매핑, UI 채널명 링크 |
| `video_duration_sec` | INTEGER | NULL |  |
| `subtitle_source` | TEXT | NULL | `manual` / `auto` |
| `created_at` | TIMESTAMP | NOT NULL, default CURRENT_TIMESTAMP |  |
| `updated_at` | TIMESTAMP | NOT NULL, on update |  |
| `completed_at` | TIMESTAMP | NULL | 종결(`completed`/`failed`) 시각 |

**Indexes**:
- `ix_video_job_youtube_video_id` — 동일 URL lookup
- `ix_video_job_status_created_at` — 최근 작업 목록 정렬
- `ix_video_job_created_at` — 페이지네이션

### `subtitle_track`

| 컬럼 | 타입 | 제약 | 비고 |
|---|---|---|---|
| `id` | UUID (TEXT) | PK |  |
| `job_id` | UUID (TEXT) | FK → `video_job.id`, NOT NULL, INDEX |  |
| `kind` | TEXT | NOT NULL | enum: `source`, `translated` |
| `language` | TEXT(2) | NOT NULL | `ko`/`ja` |
| `origin` | TEXT | NOT NULL | enum: `manual`, `auto`, `generated` (번역 결과) |
| `source_format` | TEXT | NULL | `srt`/`vtt`. translated 트랙은 NULL |
| `file_path` | TEXT | NULL | 원본 SRT/VTT 파일 보존 경로 (디버깅) |
| `cue_count` | INTEGER | NOT NULL, default 0 |  |
| `created_at` | TIMESTAMP | NOT NULL |  |

**Indexes**:
- `ix_subtitle_track_job_id_kind` — 한 작업의 source/translated 트랙 lookup

### `subtitle_cue`

| 컬럼 | 타입 | 제약 | 비고 |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT |  |
| `track_id` | UUID (TEXT) | FK → `subtitle_track.id`, NOT NULL, INDEX |  |
| `sequence` | INTEGER | NOT NULL | 1부터, track 내 unique |
| `start_ms` | INTEGER | NOT NULL | 0 이상 |
| `end_ms` | INTEGER | NOT NULL | `end_ms > start_ms` |
| `text` | TEXT | NOT NULL | 정규화된 본문(개행 LF) |

**Indexes / 제약**:
- `uq_subtitle_cue_track_sequence` (UNIQUE `track_id, sequence`)
- `ix_subtitle_cue_track_start_ms` — seek 기반 조회
- CHECK `end_ms > start_ms`

### `translation_task`

| 컬럼 | 타입 | 제약 | 비고 |
|---|---|---|---|
| `id` | UUID (TEXT) | PK |  |
| `job_id` | UUID (TEXT) | FK → `video_job.id`, NOT NULL |  |
| `source_track_id` | UUID (TEXT) | FK → `subtitle_track.id`, NOT NULL |  |
| `target_track_id` | UUID (TEXT) | FK → `subtitle_track.id`, NULL → NOT NULL (생성 후) |  |
| `total_chunks` | INTEGER | NOT NULL, default 0 |  |
| `completed_chunks` | INTEGER | NOT NULL, default 0 |  |
| `retry_count` | INTEGER | NOT NULL, default 0 |  |
| `provider_id` | TEXT | NOT NULL | 예: `claude:premium-seat` |
| `status` | TEXT | NOT NULL | enum: `queued`, `running`, `succeeded`, `failed` |
| `created_at` | TIMESTAMP | NOT NULL |  |
| `updated_at` | TIMESTAMP | NOT NULL, on update |  |

### `render_task`

| 컬럼 | 타입 | 제약 | 비고 |
|---|---|---|---|
| `id` | UUID (TEXT) | PK |  |
| `job_id` | UUID (TEXT) | FK → `video_job.id`, NOT NULL |  |
| `format` | TEXT | NOT NULL | enum: `dual_srt`, `dual_vtt` |
| `output_path` | TEXT | NULL | 완료 후 path |
| `status` | TEXT | NOT NULL | enum: `queued`, `running`, `succeeded`, `failed` |
| `created_at` | TIMESTAMP | NOT NULL |  |
| `updated_at` | TIMESTAMP | NOT NULL, on update |  |

> 같은 job에 대해 dual SRT·dual VTT 두 행이 존재할 수 있다.

### `video_asset`

| 컬럼 | 타입 | 제약 | 비고 |
|---|---|---|---|
| `id` | UUID (TEXT) | PK |  |
| `job_id` | UUID (TEXT) | FK → `video_job.id`, NOT NULL |  |
| `kind` | TEXT | NOT NULL | enum: `video_mp4`, `dual_srt`, `dual_vtt`, `original_subtitle`, `thumbnail` |
| `path` | TEXT | NOT NULL | 파일시스템 경로 (`var/storage/...` 상대) |
| `mime_type` | TEXT | NOT NULL |  |
| `byte_size` | INTEGER | NOT NULL |  |
| `created_at` | TIMESTAMP | NOT NULL |  |

**Indexes**: `ix_video_asset_job_id_kind`

### `job_event`

| 컬럼 | 타입 | 제약 | 비고 |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT |  |
| `job_id` | UUID (TEXT) | FK → `video_job.id`, NOT NULL, INDEX |  |
| `event_type` | TEXT | NOT NULL | `state_changed` / `progress` / `error` / `info` |
| `payload` | TEXT (JSON) | NOT NULL | SSE로 push되는 payload와 동일 형식 |
| `created_at` | TIMESTAMP | NOT NULL, INDEX |  |

> 감사·디버깅용. SSE 재연결 시 last-event-id 이후를 replay할 수 있는 토대 제공.

## 상태 머신 (`video_job.status`)

```
pending ──> downloading ──> subtitle_processing ──> translating ──> rendering ──> completed
   │            │                    │                    │             │
   └────────────┴────────────────────┴────────────────────┴─────────────┴───> failed
```

- 종결 상태: `completed`, `failed`. 자동 재시작 없음.
- 정상 전이는 단방향. 같은 단계 내 재시도는 status를 유지하고 `retry_count`/`progress`만 갱신.
- 사용자 취소는 `failed`로 전이하고 `error_code=USER_CANCELLED`.

### 전이 규칙 (서비스 계층에서 강제)

| from | to | 트리거 |
|---|---|---|
| `pending` | `downloading` | download task 시작 |
| `downloading` | `subtitle_processing` | download 성공 |
| `subtitle_processing` | `translating` | source 트랙 정규화 + target 결정 완료 |
| `translating` | `rendering` | translated 트랙 cue 100% 저장 |
| `rendering` | `completed` | dual SRT/VTT 모두 생성, video_asset 등록 |
| 임의 | `failed` | 단계 task의 unrecoverable 예외 |

전이 외 변경 시도는 `IllegalStateTransitionError`로 거절(서비스 계층 단위 테스트로 검증).

## Pydantic 도메인 모델 (개요)

```python
# app/domain/jobs/states.py
class JobStatus(str, Enum):
    pending = "pending"
    downloading = "downloading"
    subtitle_processing = "subtitle_processing"
    translating = "translating"
    rendering = "rendering"
    completed = "completed"
    failed = "failed"

# app/domain/jobs/models.py
class VideoJob(BaseModel):
    id: JobId
    source_url: HttpUrl
    youtube_video_id: str = Field(min_length=11, max_length=11)
    source_language: Lang | None = None
    target_language: Lang | None = None
    status: JobStatus
    error_stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata: VideoMetadata
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

class VideoMetadata(BaseModel):
    title: str | None
    channel: str | None
    duration_sec: int | None
    subtitle_source: Literal["manual", "auto"] | None

# app/domain/subtitles/models.py
class SubtitleCue(BaseModel):
    sequence: int = Field(ge=1)
    start_ms: int = Field(ge=0)
    end_ms: int
    text: str

    @model_validator(mode="after")
    def _check_range(self) -> "SubtitleCue":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self
```

> ORM 클래스는 `app/infrastructure/db/orm.py`. 도메인 모델은 ORM과 분리되어 변환 함수
> (`to_domain`, `to_orm`)로 매핑한다 — 헌법 II(Layered) 준수.

## Migration 정책

- Alembic 사용. 마이그레이션은 PR 단위 단일 파일.
- 모든 마이그레이션은 PostgreSQL에서도 그대로 실행 가능해야 한다(데이터 타입 호환 확인).
- SQLite에서 `ALTER TABLE` 한계 우회는 Alembic의 `batch_alter_table` 사용.

## 데이터 보존 정책

- MVP는 명시적 보존 정책 없음(spec Assumptions). DB·파일 모두 사용자가 임의로 정리.
- `JobEvent`는 누적될 수 있으므로 단일 `job_id`당 최대 1000건으로 캡(서비스 계층에서 가장 오래된 행 정리). 운영 사용 전 결정값은 환경변수로 노출.

## 인덱스 / 쿼리 패턴

| 쿼리 | 인덱스 |
|---|---|
| 동일 URL 재요청 lookup | `video_job(youtube_video_id, status)` (covering index 후속 검토) |
| 최근 작업 목록(상태 + 최신순) | `video_job(status, created_at DESC)` |
| 작업 상세 + 트랙 / cue | `subtitle_track(job_id, kind)`, `subtitle_cue(track_id, sequence)` |
| cue seek (start_ms 기준) | `subtitle_cue(track_id, start_ms)` |
| SSE 이벤트 replay | `job_event(job_id, id DESC)` |
