"""초기 스키마 — 7개 테이블 생성.

data-model.md에 정의된 video_job, subtitle_track, subtitle_cue,
translation_task, render_task, video_asset, job_event 테이블과
모든 인덱스를 생성한다.

PostgreSQL portable 타입만 사용하며 SQLite-specific 타입은 포함하지 않는다.

Revision ID: 0001
Revises: (없음 — 최초 마이그레이션)
Create Date: 2026-05-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """7개 테이블 및 인덱스 생성."""

    # ── 1. video_job ─────────────────────────────────────────────────────────
    op.create_table(
        "video_job",
        sa.Column("id", sa.String(26), nullable=False),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("youtube_video_id", sa.Text, nullable=False),
        sa.Column("source_language", sa.String(2), nullable=True),
        sa.Column("target_language", sa.String(2), nullable=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("error_stage", sa.Text, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("error_code", sa.Text, nullable=True),
        sa.Column("video_title", sa.Text, nullable=True),
        sa.Column("video_channel", sa.Text, nullable=True),
        sa.Column("video_duration_sec", sa.Integer, nullable=True),
        sa.Column("subtitle_source", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_video_job_youtube_video_id", "video_job", ["youtube_video_id"])
    op.create_index(
        "ix_video_job_status_created_at", "video_job", ["status", "created_at"]
    )
    op.create_index("ix_video_job_created_at", "video_job", ["created_at"])

    # ── 2. subtitle_track ─────────────────────────────────────────────────────
    op.create_table(
        "subtitle_track",
        sa.Column("id", sa.String(26), nullable=False),
        sa.Column("job_id", sa.String(26), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("language", sa.String(2), nullable=False),
        sa.Column("origin", sa.Text, nullable=False),
        sa.Column("source_format", sa.Text, nullable=True),
        sa.Column("file_path", sa.Text, nullable=True),
        sa.Column("cue_count", sa.Integer, server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["video_job.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_subtitle_track_job_id_kind", "subtitle_track", ["job_id", "kind"]
    )

    # ── 3. subtitle_cue ───────────────────────────────────────────────────────
    op.create_table(
        "subtitle_cue",
        sa.Column("id", sa.Integer, autoincrement=True, nullable=False),
        sa.Column("track_id", sa.String(26), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("start_ms", sa.Integer, nullable=False),
        sa.Column("end_ms", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.CheckConstraint("end_ms > start_ms", name="ck_subtitle_cue_end_after_start"),
        sa.ForeignKeyConstraint(["track_id"], ["subtitle_track.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("track_id", "sequence", name="uq_subtitle_cue_track_sequence"),
    )
    op.create_index(
        "ix_subtitle_cue_track_start_ms", "subtitle_cue", ["track_id", "start_ms"]
    )

    # ── 4. translation_task ───────────────────────────────────────────────────
    op.create_table(
        "translation_task",
        sa.Column("id", sa.String(26), nullable=False),
        sa.Column("job_id", sa.String(26), nullable=False),
        sa.Column("source_track_id", sa.String(26), nullable=False),
        sa.Column("target_track_id", sa.String(26), nullable=True),
        sa.Column("total_chunks", sa.Integer, server_default="0", nullable=False),
        sa.Column("completed_chunks", sa.Integer, server_default="0", nullable=False),
        sa.Column("retry_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("provider_id", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["video_job.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_track_id"], ["subtitle_track.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_track_id"], ["subtitle_track.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 5. render_task ────────────────────────────────────────────────────────
    op.create_table(
        "render_task",
        sa.Column("id", sa.String(26), nullable=False),
        sa.Column("job_id", sa.String(26), nullable=False),
        sa.Column("format", sa.Text, nullable=False),
        sa.Column("output_path", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["video_job.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── 6. video_asset ────────────────────────────────────────────────────────
    op.create_table(
        "video_asset",
        sa.Column("id", sa.String(26), nullable=False),
        sa.Column("job_id", sa.String(26), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("mime_type", sa.Text, nullable=False),
        sa.Column("byte_size", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["video_job.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_video_asset_job_id_kind", "video_asset", ["job_id", "kind"])

    # ── 7. job_event ──────────────────────────────────────────────────────────
    op.create_table(
        "job_event",
        sa.Column("id", sa.Integer, autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(26), nullable=False),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["video_job.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_event_job_id", "job_event", ["job_id"])
    op.create_index("ix_job_event_created_at", "job_event", ["created_at"])


def downgrade() -> None:
    """7개 테이블 및 인덱스 삭제 (의존 순서의 역순)."""

    # job_event
    op.drop_index("ix_job_event_created_at", table_name="job_event")
    op.drop_index("ix_job_event_job_id", table_name="job_event")
    op.drop_table("job_event")

    # video_asset
    op.drop_index("ix_video_asset_job_id_kind", table_name="video_asset")
    op.drop_table("video_asset")

    # render_task
    op.drop_table("render_task")

    # translation_task
    op.drop_table("translation_task")

    # subtitle_cue
    op.drop_index("ix_subtitle_cue_track_start_ms", table_name="subtitle_cue")
    op.drop_table("subtitle_cue")

    # subtitle_track
    op.drop_index("ix_subtitle_track_job_id_kind", table_name="subtitle_track")
    op.drop_table("subtitle_track")

    # video_job
    op.drop_index("ix_video_job_created_at", table_name="video_job")
    op.drop_index("ix_video_job_status_created_at", table_name="video_job")
    op.drop_index("ix_video_job_youtube_video_id", table_name="video_job")
    op.drop_table("video_job")
