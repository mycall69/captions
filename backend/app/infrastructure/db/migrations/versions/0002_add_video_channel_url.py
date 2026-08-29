"""video_job 테이블에 video_channel_url 컬럼 추가.

UI 채널명 링크용 채널 페이지 URL — yt-dlp `channel_url` (fallback: `uploader_url`)
매핑. 기존 행은 NULL 로 채워지며, 다음 메타데이터 fetch 시 갱신된다.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """video_job.video_channel_url 컬럼 추가 (nullable)."""
    op.add_column(
        "video_job",
        sa.Column("video_channel_url", sa.Text, nullable=True),
    )


def downgrade() -> None:
    """video_job.video_channel_url 컬럼 제거."""
    op.drop_column("video_job", "video_channel_url")
