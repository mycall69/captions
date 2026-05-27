"""T022: VideoJob 및 VideoMetadata Pydantic 도메인 모델.

contracts/openapi.yaml의 Job / VideoMetadata 스키마와 필드명·제약이 일치해야 한다.
ORM 클래스(app/infrastructure/db/orm.py)와 분리되며, to_domain / to_orm 변환 함수로 매핑.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

from app.domain.jobs.states import JobStatus

# 지원 언어 타입 — app.domain.translation.provider 에서 재수출(canonical 정의는 여기)
Lang = Literal["ko", "ja"]

# 자막 출처 타입
SubtitleSource = Literal["manual", "auto"]


class VideoMetadata(BaseModel):
    """비디오 메타데이터 — yt-dlp 수집 결과.

    openapi.yaml VideoMetadata 스키마와 1:1 대응.
    """

    title: str | None = None
    channel: str | None = None
    duration_sec: int | None = None
    subtitle_source: SubtitleSource | None = None


class VideoJob(BaseModel):
    """비디오 번역 작업 도메인 모델.

    openapi.yaml Job 스키마와 1:1 대응.
    id는 26자 ULID, youtube_video_id는 11자 고정.
    """

    # 식별자
    id: str = Field(min_length=26, max_length=26)
    """26자 ULID — 클라이언트 노출 ID."""

    source_url: HttpUrl
    """정규화된 YouTube 영상 URL."""

    youtube_video_id: str = Field(min_length=11, max_length=11)
    """11자 YouTube 영상 ID — 동일 URL 재요청 lookup 키."""

    # 언어
    source_language: Lang | None = None
    """원본 자막 언어 — 자막 추출 완료 후 확정."""

    target_language: Lang | None = None
    """번역 목표 언어 — source 결정 시 자동 산정(ko↔ja)."""

    # 상태
    status: JobStatus
    """현재 처리 단계."""

    progress: float | None = Field(default=None, ge=0.0, le=1.0)
    """현재 단계 진행률 0~1 (단계 전이 시 0으로 리셋)."""

    # 오류 정보 (실패 시 기록)
    error_stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    # 메타데이터
    metadata: VideoMetadata

    # 타임스탬프
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    """종결(completed/failed) 시각."""

    # 재사용 여부 (생성 응답에만 의미 있음)
    reused: bool = False
