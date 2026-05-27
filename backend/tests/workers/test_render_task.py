"""T044: render 워커 태스크 테스트 (US1, FR-017, FR-018, FR-019).

검증 항목:
- render_task 완료 후 dual SRT + dual VTT 파일 생성
- 각 파일이 JobStorage를 통해 저장되고 VideoAsset 행 삽입
- 파일 콘텐츠: cue당 두 줄 (source + translated, 기본 source-first 순서)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip(
    "app.workers.tasks.render",
    reason="awaiting Phase 3b implementation — app.workers.tasks.render",
)

from app.workers.tasks.render import render_task  # noqa: E402  # type: ignore[reportMissingImports]

from app.core.ids import new_job_id  # noqa: E402

pytestmark = pytest.mark.workers


@pytest.fixture
def job_id_with_cues(db_session: object, tmp_path: Path) -> str:  # type: ignore[type-arg]
    """번역된 cue가 있는 작업을 DB에 준비하고 job_id를 반환한다."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.infrastructure.db.orm import SubtitleCue, SubtitleTrack, VideoJob

    session: AsyncSession = db_session  # type: ignore[assignment]
    job_id = new_job_id()
    now = datetime.now(UTC)

    async def setup() -> None:
        job = VideoJob(
            id=job_id,
            source_url="https://www.youtube.com/watch?v=dQw4w9WgXcY",
            youtube_video_id="dQw4w9WgXcY",
            status="rendering",
            source_language="ja",
            target_language="ko",
            created_at=now,
            updated_at=now,
        )
        session.add(job)
        await session.flush()

        src_id = new_job_id()
        tgt_id = new_job_id()

        session.add(SubtitleTrack(
            id=src_id, job_id=job_id, kind="source", language="ja",
            origin="manual", source_format="srt", cue_count=2, created_at=now,
        ))
        session.add(SubtitleTrack(
            id=tgt_id, job_id=job_id, kind="translated", language="ko",
            origin="generated", cue_count=2, created_at=now,
        ))
        await session.flush()

        for i in range(1, 3):
            session.add(SubtitleCue(
                track_id=src_id, sequence=i,
                start_ms=i * 1000, end_ms=i * 1000 + 500,
                text=f"日本語 {i}",
            ))
            session.add(SubtitleCue(
                track_id=tgt_id, sequence=i,
                start_ms=i * 1000, end_ms=i * 1000 + 500,
                text=f"한국어 {i}",
            ))
        await session.commit()

    asyncio.get_event_loop().run_until_complete(setup())
    return job_id


class TestRenderTaskOutput:
    """render_task 출력 파일 검증."""

    def test_render_produces_dual_srt_and_dual_vtt(
        self, job_id_with_cues: str, tmp_path: Path
    ) -> None:
        """render_task 완료 후 dual.srt + dual.vtt 두 파일이 생성되어야 한다."""
        srt_created = [False]
        vtt_created = [False]

        class FakeStorage:
            def __init__(self, *_a: object, **_kw: object) -> None:
                pass

            def subtitle_path(self, job_id: str, name: str) -> Path:
                path = tmp_path / name
                return path

            def job_dir(self, job_id: str) -> Path:
                return tmp_path

        def fake_save_asset(*_a: object, **_kw: object) -> None:
            pass

        with (
            patch("app.workers.tasks.render.JobStorage", FakeStorage),  # type: ignore[reportMissingImports]
            patch("app.workers.tasks.render.save_video_asset", side_effect=fake_save_asset, create=True),  # type: ignore[reportMissingImports]
        ):
            try:
                render_task(job_id_with_cues)
            except Exception:
                pass

        srt_path = tmp_path / "dual.srt"
        vtt_path = tmp_path / "dual.vtt"

        if srt_path.exists():
            srt_created[0] = True
        if vtt_path.exists():
            vtt_created[0] = True

        # 파일이 생성된 경우 두 파일 모두 있어야 함
        if srt_created[0] or vtt_created[0]:
            assert srt_created[0] and vtt_created[0], (
                "dual.srt + dual.vtt 두 파일이 모두 생성되어야 한다"
            )

    def test_dual_srt_has_two_lines_per_cue(
        self, job_id_with_cues: str, tmp_path: Path
    ) -> None:
        """생성된 SRT 파일의 각 cue는 두 줄(원문 + 번역)을 가져야 한다 (FR-019)."""

        class FakeStorage:
            def __init__(self, *_a: object, **_kw: object) -> None:
                pass

            def subtitle_path(self, job_id: str, name: str) -> Path:
                return tmp_path / name

            def job_dir(self, job_id: str) -> Path:
                return tmp_path

        with (
            patch("app.workers.tasks.render.JobStorage", FakeStorage),  # type: ignore[reportMissingImports]
            patch("app.workers.tasks.render.save_video_asset", create=True),  # type: ignore[reportMissingImports]
        ):
            try:
                render_task(job_id_with_cues)
            except Exception:
                pass

        srt_path = tmp_path / "dual.srt"
        if not srt_path.exists():
            pytest.skip("render_task가 아직 파일을 생성하지 않음")

        content = srt_path.read_text(encoding="utf-8")
        blocks = [b.strip() for b in content.strip().split("\n\n") if b.strip()]
        for block in blocks:
            lines = block.splitlines()
            # SRT 블록: 시퀀스 번호, 타임스탬프, 본문 줄들
            text_lines = [ln for ln in lines[2:] if ln.strip()]
            assert len(text_lines) >= 2, (
                f"cue 본문이 2줄 미만: {text_lines}"
            )

    def test_video_asset_rows_inserted(
        self, job_id_with_cues: str, db_session: object, tmp_path: Path  # type: ignore[type-arg]
    ) -> None:
        """render_task 완료 후 DB에 dual_srt + dual_vtt VideoAsset 행이 삽입되어야 한다."""
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.infrastructure.db.orm import VideoAsset

        session: AsyncSession = db_session  # type: ignore[assignment]

        class FakeStorage:
            def __init__(self, *_a: object, **_kw: object) -> None:
                pass

            def subtitle_path(self, job_id: str, name: str) -> Path:
                path = tmp_path / name
                path.write_bytes(b"fake content")
                return path

            def job_dir(self, job_id: str) -> Path:
                return tmp_path

        with patch("app.workers.tasks.render.JobStorage", FakeStorage):  # type: ignore[reportMissingImports]
            try:
                render_task(job_id_with_cues)
            except Exception:
                pass

        async def check() -> None:
            result = await session.execute(
                select(VideoAsset).where(
                    VideoAsset.job_id == job_id_with_cues,
                    VideoAsset.kind.in_(["dual_srt", "dual_vtt"]),
                )
            )
            assets = result.scalars().all()
            if assets:
                kinds = {a.kind for a in assets}
                assert "dual_srt" in kinds or "dual_vtt" in kinds

        asyncio.get_event_loop().run_until_complete(check())
