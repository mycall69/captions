"""T045: End-to-end Celery chain 테스트 (US1, plan.md §Sequence).

검증 항목:
- download → extract_subtitles → translate → render 순서대로 실행
- FakeTranslationProvider 사용
- 최종 작업 상태가 completed
- 각 단계별 DB 상태 + 산출물 존재 확인
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

pytest.importorskip(
    "app.workers.tasks.download",
    reason="awaiting Phase 3b implementation",
)
pytest.importorskip(
    "app.workers.tasks.extract_subtitles",
    reason="awaiting Phase 3b implementation",
)
pytest.importorskip(
    "app.workers.tasks.translate",
    reason="awaiting Phase 3b implementation",
)
pytest.importorskip(
    "app.workers.tasks.render",
    reason="awaiting Phase 3b implementation",
)
pytest.importorskip(
    "app.workers.pipeline",
    reason="awaiting Phase 3b implementation — app.workers.pipeline (chain 조립)",
)

from app.workers.pipeline import build_job_chain  # noqa: E402  # type: ignore[reportMissingImports]

from app.core.ids import new_job_id  # noqa: E402
from app.infrastructure.db.orm import VideoJob  # noqa: E402
from tests.fixtures.fake_provider import FakeTranslationProvider  # noqa: E402

pytestmark = pytest.mark.workers


@pytest_asyncio.fixture
async def pending_job(db_session: object) -> str:  # type: ignore[type-arg]
    """pending 상태 작업을 DB에 삽입하고 job_id를 반환한다."""
    from sqlalchemy.ext.asyncio import AsyncSession

    session: AsyncSession = db_session  # type: ignore[assignment]
    job_id = new_job_id()
    now = datetime.now(UTC)

    job = VideoJob(
        id=job_id,
        source_url="https://www.youtube.com/watch?v=dQw4w9WgXcY",
        youtube_video_id="dQw4w9WgXcY",
        status="pending",
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    await session.commit()

    return job_id


class TestPipelineChain:
    """전체 파이프라인 체인 end-to-end 테스트."""

    async def test_chain_completes_with_fake_provider(
        self, pending_job: str, tmp_path: Path, db_session: object
    ) -> None:
        """FakeProvider를 사용한 전체 체인이 completed 상태로 종료되어야 한다."""
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        session: AsyncSession = db_session  # type: ignore[assignment]
        provider = FakeTranslationProvider()

        # 파일시스템 mock: 각 단계가 실제 파일을 쓰는 것처럼 설정
        fake_video = tmp_path / "video.mp4"
        fake_video.write_bytes(b"\x00" * 1024)

        fake_subtitle = tmp_path / "source.ja.vtt"
        fake_subtitle.write_text(
            "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nこんにちは、世界。\n",
            encoding="utf-8",
        )

        with (
            patch("app.workers.tasks.translate.get_translation_provider", return_value=provider),  # type: ignore[reportMissingImports]
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
        ):
            result_chain = build_job_chain(pending_job)
            result_chain.apply()  # Celery eager mode에서 실행

        result = await session.execute(
            select(VideoJob).where(VideoJob.id == pending_job)
        )
        job = result.scalar_one_or_none()
        assert job is not None
        assert job.status == "completed", (
            f"파이프라인 체인 완료 후 job.status가 'completed'여야 한다, 실제: {job.status}"
        )

    async def test_chain_stages_execute_in_order(self, pending_job: str) -> None:
        """체인이 download → extract → translate → render 순서로 실행되어야 한다."""
        stage_order: list[str] = []

        def fake_download(job_id: str) -> str:
            stage_order.append("download")
            return job_id

        def fake_extract(job_id: str) -> str:
            stage_order.append("extract")
            return job_id

        def fake_translate(job_id: str) -> str:
            stage_order.append("translate")
            return job_id

        def fake_render(job_id: str) -> str:
            stage_order.append("render")
            return job_id

        with (
            patch("app.workers.tasks.download.download_task", side_effect=fake_download),  # type: ignore[reportMissingImports]
            patch("app.workers.tasks.extract_subtitles.extract_subtitles_task", side_effect=fake_extract),  # type: ignore[reportMissingImports]
            patch("app.workers.tasks.translate.translate_task", side_effect=fake_translate),  # type: ignore[reportMissingImports]
            patch("app.workers.tasks.render.render_task", side_effect=fake_render),  # type: ignore[reportMissingImports]
        ):
            result_chain = build_job_chain(pending_job)
            result_chain.apply()

        expected_order = ["download", "extract", "translate", "render"]
        assert stage_order == expected_order, (
            f"단계 순서 오류: {stage_order} (예상: {expected_order})"
        )

    async def test_completed_job_has_assets(self, pending_job: str, db_session: object) -> None:  # type: ignore[type-arg]
        """파이프라인 완료 후 VideoAsset 행이 존재해야 한다."""
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.infrastructure.db.orm import VideoAsset

        session: AsyncSession = db_session  # type: ignore[assignment]
        provider = FakeTranslationProvider()

        with patch(
            "app.workers.tasks.translate.get_translation_provider", return_value=provider  # type: ignore[reportMissingImports]
        ):
            result_chain = build_job_chain(pending_job)
            result_chain.apply()

        result = await session.execute(
            select(VideoAsset).where(VideoAsset.job_id == pending_job)
        )
        assets = result.scalars().all()
        kinds = {a.kind for a in assets}
        assert "dual_srt" in kinds or "dual_vtt" in kinds or "video_mp4" in kinds, (
            f"파이프라인 완료 후 VideoAsset 행이 없거나 예상된 kind가 없다, 실제: {kinds}"
        )
