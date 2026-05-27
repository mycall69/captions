"""T017: SQLAlchemy 2.x ORM 매핑 — 7개 테이블.

data-model.md에 정의된 스키마를 그대로 구현한다.
PostgreSQL portable 타입만 사용하며 SQLite-specific 타입은 금지된다.

상태(status, kind, origin 등) 컬럼은 String 타입으로 저장하고,
허용 값은 주석으로 명시한다. 입력 검증은 Pydantic 도메인 모델이 담당한다 (헌법 II).

FK ondelete="CASCADE": 부모 video_job 삭제 시 모든 자식 행이 자동 삭제된다.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# ── Base 클래스 ────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    """모든 ORM 모델의 기반 클래스."""

    pass


# ── 1. video_job ──────────────────────────────────────────────────────────────

class VideoJob(Base):
    """동영상 처리 작업 메타데이터.

    status 허용 값: pending | downloading | subtitle_processing |
                    translating | rendering | completed | failed
    subtitle_source 허용 값: manual | auto
    """

    __tablename__ = "video_job"

    # PK: ULID를 TEXT(26)으로 저장
    id: Mapped[str] = mapped_column(String(26), primary_key=True)

    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    youtube_video_id: Mapped[str] = mapped_column(Text, nullable=False)

    # 자막 추출 완료 후 확정 (ko / ja)
    source_language: Mapped[str | None] = mapped_column(String(2), nullable=True)
    target_language: Mapped[str | None] = mapped_column(String(2), nullable=True)

    # 상태 머신 (data-model.md §상태 머신)
    status: Mapped[str] = mapped_column(Text, nullable=False)

    # 실패 정보
    error_stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)

    # yt-dlp 메타데이터
    video_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_channel: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # subtitle_source 허용 값: manual | auto
    subtitle_source: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # 관계
    subtitle_tracks: Mapped[list[SubtitleTrack]] = relationship(
        "SubtitleTrack", back_populates="job", cascade="all, delete-orphan"
    )
    translation_tasks: Mapped[list[TranslationTask]] = relationship(
        "TranslationTask", back_populates="job", cascade="all, delete-orphan"
    )
    render_tasks: Mapped[list[RenderTask]] = relationship(
        "RenderTask", back_populates="job", cascade="all, delete-orphan"
    )
    video_assets: Mapped[list[VideoAsset]] = relationship(
        "VideoAsset", back_populates="job", cascade="all, delete-orphan"
    )
    job_events: Mapped[list[JobEvent]] = relationship(
        "JobEvent", back_populates="job", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # data-model.md §Indexes
        Index("ix_video_job_youtube_video_id", "youtube_video_id"),
        Index("ix_video_job_status_created_at", "status", "created_at"),
        Index("ix_video_job_created_at", "created_at"),
    )


# ── 2. subtitle_track ─────────────────────────────────────────────────────────

class SubtitleTrack(Base):
    """자막 트랙.

    kind 허용 값: source | translated
    origin 허용 값: manual | auto | generated
    source_format 허용 값: srt | vtt (translated 트랙은 NULL)
    """

    __tablename__ = "subtitle_track"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("video_job.id", ondelete="CASCADE"),
        nullable=False,
    )

    # kind 허용 값: source | translated
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(2), nullable=False)

    # origin 허용 값: manual | auto | generated
    origin: Mapped[str] = mapped_column(Text, nullable=False)

    # source_format 허용 값: srt | vtt
    source_format: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 원본 파일 경로 (디버깅용 보존)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    cue_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # 관계
    job: Mapped[VideoJob] = relationship("VideoJob", back_populates="subtitle_tracks")
    cues: Mapped[list[SubtitleCue]] = relationship(
        "SubtitleCue", back_populates="track", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_subtitle_track_job_id_kind", "job_id", "kind"),
    )


# ── 3. subtitle_cue ───────────────────────────────────────────────────────────

class SubtitleCue(Base):
    """개별 자막 큐 (타임스탬프 + 본문).

    end_ms > start_ms CHECK 제약이 DB 레벨에서 시행된다.
    """

    __tablename__ = "subtitle_cue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    track_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("subtitle_track.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    # 관계
    track: Mapped[SubtitleTrack] = relationship("SubtitleTrack", back_populates="cues")

    __table_args__ = (
        # track 내 sequence 유일성 보장
        UniqueConstraint("track_id", "sequence", name="uq_subtitle_cue_track_sequence"),
        # seek 기반 조회 최적화
        Index("ix_subtitle_cue_track_start_ms", "track_id", "start_ms"),
        # end_ms > start_ms DB 레벨 강제 (PostgreSQL portable)
        CheckConstraint("end_ms > start_ms", name="ck_subtitle_cue_end_after_start"),
    )


# ── 4. translation_task ───────────────────────────────────────────────────────

class TranslationTask(Base):
    """번역 처리 작업.

    status 허용 값: queued | running | succeeded | failed
    """

    __tablename__ = "translation_task"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("video_job.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_track_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("subtitle_track.id", ondelete="CASCADE"),
        nullable=False,
    )
    # target_track_id: 번역 트랙 생성 후 NOT NULL로 갱신됨
    target_track_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("subtitle_track.id", ondelete="CASCADE"),
        nullable=True,
    )

    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    completed_chunks: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # 예: claude:premium-seat
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)

    # status 허용 값: queued | running | succeeded | failed
    status: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # 관계
    job: Mapped[VideoJob] = relationship("VideoJob", back_populates="translation_tasks")


# ── 5. render_task ────────────────────────────────────────────────────────────

class RenderTask(Base):
    """자막 렌더링 작업.

    format 허용 값: dual_srt | dual_vtt
    status 허용 값: queued | running | succeeded | failed
    """

    __tablename__ = "render_task"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("video_job.id", ondelete="CASCADE"),
        nullable=False,
    )

    # format 허용 값: dual_srt | dual_vtt
    format: Mapped[str] = mapped_column(Text, nullable=False)

    # 렌더링 완료 후 파일 경로 기록
    output_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # status 허용 값: queued | running | succeeded | failed
    status: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # 관계
    job: Mapped[VideoJob] = relationship("VideoJob", back_populates="render_tasks")


# ── 6. video_asset ────────────────────────────────────────────────────────────

class VideoAsset(Base):
    """처리 결과 파일 자산 (video_mp4, dual_srt, dual_vtt 등).

    kind 허용 값: video_mp4 | dual_srt | dual_vtt | original_subtitle | thumbnail
    path: var/storage/... 상대 경로
    """

    __tablename__ = "video_asset"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("video_job.id", ondelete="CASCADE"),
        nullable=False,
    )

    # kind 허용 값: video_mp4 | dual_srt | dual_vtt | original_subtitle | thumbnail
    kind: Mapped[str] = mapped_column(Text, nullable=False)

    # var/storage/... 상대 경로
    path: Mapped[str] = mapped_column(Text, nullable=False)

    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # 관계
    job: Mapped[VideoJob] = relationship("VideoJob", back_populates="video_assets")

    __table_args__ = (
        Index("ix_video_asset_job_id_kind", "job_id", "kind"),
    )


# ── 7. job_event ──────────────────────────────────────────────────────────────

class JobEvent(Base):
    """작업 이벤트 감사 로그.

    SSE 재연결 시 last-event-id 이후를 replay하는 데 사용된다.
    event_type 허용 값: job.state_changed | job.progress | job.completed | job.failed | job.info
    payload: SSE push payload와 동일 형식의 JSON 문자열
    """

    __tablename__ = "job_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("video_job.id", ondelete="CASCADE"),
        nullable=False,
    )

    # event_type 허용 값: job.state_changed | job.progress | job.completed | job.failed | job.info
    event_type: Mapped[str] = mapped_column(Text, nullable=False)

    # SSE payload와 동일 형식의 JSON (Text 컬럼에 JSON 직렬화 저장)
    payload: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # 관계
    job: Mapped[VideoJob] = relationship("VideoJob", back_populates="job_events")

    __table_args__ = (
        Index("ix_job_event_job_id", "job_id"),
        Index("ix_job_event_created_at", "created_at"),
    )


# 미사용 import 억제 (Boolean, PG_JSON은 향후 마이그레이션에서 사용 가능)
__all__ = [
    "Base",
    "VideoJob",
    "SubtitleTrack",
    "SubtitleCue",
    "TranslationTask",
    "RenderTask",
    "VideoAsset",
    "JobEvent",
]
