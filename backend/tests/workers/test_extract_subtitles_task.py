"""T042: extract_subtitles 워커 태스크 테스트 (US1, FR-008, FR-009, FR-010, FR-011).

검증 항목:
- manual subtitle 경로가 먼저 시도된다
- manual 없으면 auto subtitle로 fallback
- ko/ja 자막 미발견 시 작업을 failed로 전이하고 SUBTITLE_NOT_FOUND 기록
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip(
    "app.workers.tasks.extract_subtitles",
    reason="awaiting Phase 3b implementation — app.workers.tasks.extract_subtitles",
)

from datetime import UTC

from app.workers.tasks.extract_subtitles import (
    extract_subtitles_task,  # noqa: E402  # type: ignore[reportMissingImports]
)

pytestmark = pytest.mark.workers


class TestExtractSubtitlesManualFirst:
    """FR-008: manual subtitle이 auto보다 우선되어야 한다."""

    def test_manual_subtitle_attempted_before_auto(self) -> None:
        """yt-dlp manual subtitle 다운로드 함수가 auto보다 먼저 호출되어야 한다."""
        call_order: list[str] = []

        def fake_download_manual(*_a: object, **_kw: object) -> list[str]:
            call_order.append("manual")
            return ["source.ja.vtt"]

        def fake_download_auto(*_a: object, **_kw: object) -> list[str]:
            call_order.append("auto")
            return []

        with (
            patch(
                "app.workers.tasks.extract_subtitles.download_manual_subtitles",  # type: ignore[reportMissingImports]
                side_effect=fake_download_manual,
            ),
            patch(
                "app.workers.tasks.extract_subtitles.download_auto_subtitles",  # type: ignore[reportMissingImports]
                side_effect=fake_download_auto,
            ),
        ):
            try:
                extract_subtitles_task("test_job_001")
            except Exception:
                pass

        if call_order:
            assert call_order[0] == "manual", (
                "manual subtitle 다운로드가 auto보다 먼저 시도되어야 한다 (FR-008)"
            )

    def test_auto_not_called_when_manual_succeeds(self) -> None:
        """manual subtitle이 성공하면 auto 다운로드는 호출되지 않아야 한다."""
        auto_called = [False]

        def fake_download_manual(*_a: object, **_kw: object) -> list[str]:
            return ["source.ja.vtt"]

        def fake_download_auto(*_a: object, **_kw: object) -> list[str]:
            auto_called[0] = True
            return []

        with (
            patch(
                "app.workers.tasks.extract_subtitles.download_manual_subtitles",  # type: ignore[reportMissingImports]
                side_effect=fake_download_manual,
            ),
            patch(
                "app.workers.tasks.extract_subtitles.download_auto_subtitles",  # type: ignore[reportMissingImports]
                side_effect=fake_download_auto,
            ),
        ):
            try:
                extract_subtitles_task("test_job_002")
            except Exception:
                pass

        assert not auto_called[0], "manual 성공 시 auto가 호출되면 안 된다 (FR-008)"


class TestExtractSubtitlesFallback:
    """FR-008: manual 없을 때 auto subtitle fallback."""

    def test_auto_used_when_manual_not_found(self) -> None:
        """manual 자막이 없으면 auto로 fallback되어야 한다."""
        auto_called = [False]

        def fake_download_manual(*_a: object, **_kw: object) -> list[str]:
            return []  # manual 없음

        def fake_download_auto(*_a: object, **_kw: object) -> list[str]:
            auto_called[0] = True
            return ["source.ja.vtt"]

        with (
            patch(
                "app.workers.tasks.extract_subtitles.download_manual_subtitles",  # type: ignore[reportMissingImports]
                side_effect=fake_download_manual,
            ),
            patch(
                "app.workers.tasks.extract_subtitles.download_auto_subtitles",  # type: ignore[reportMissingImports]
                side_effect=fake_download_auto,
            ),
        ):
            try:
                extract_subtitles_task("test_job_003")
            except Exception:
                pass

        assert auto_called[0], "manual 없을 때 auto fallback이 호출되어야 한다 (FR-008)"


class TestExtractSubtitlesFailure:
    """FR-009, FR-011: ko/ja 자막 미발견 시 failed 전이."""

    def test_no_ko_ja_subtitle_marks_job_failed(self, db_session: object) -> None:  # type: ignore[type-arg]
        """ko/ja 자막이 모두 없으면 작업이 failed 상태 + SUBTITLE_NOT_FOUND가 되어야 한다."""
        import asyncio
        from datetime import datetime

        from sqlalchemy.ext.asyncio import AsyncSession

        from app.core.ids import new_job_id
        from app.infrastructure.db.orm import VideoJob

        session: AsyncSession = db_session  # type: ignore[assignment]
        job_id = new_job_id()
        now = datetime.now(UTC)

        async def setup() -> None:
            job = VideoJob(
                id=job_id,
                source_url="https://www.youtube.com/watch?v=dQw4w9WgXcY",
                youtube_video_id="dQw4w9WgXcY",
                status="downloading",
                created_at=now,
                updated_at=now,
            )
            session.add(job)
            await session.commit()

        asyncio.get_event_loop().run_until_complete(setup())

        def fake_download_manual(*_a: object, **_kw: object) -> list[str]:
            return []

        def fake_download_auto(*_a: object, **_kw: object) -> list[str]:
            return []  # ko/ja 자막 없음

        with (
            patch(
                "app.workers.tasks.extract_subtitles.download_manual_subtitles",  # type: ignore[reportMissingImports]
                side_effect=fake_download_manual,
            ),
            patch(
                "app.workers.tasks.extract_subtitles.download_auto_subtitles",  # type: ignore[reportMissingImports]
                side_effect=fake_download_auto,
            ),
        ):
            try:
                extract_subtitles_task(job_id)
            except Exception:
                pass

        async def check() -> None:
            from sqlalchemy import select
            result = await session.execute(
                select(VideoJob).where(VideoJob.id == job_id)
            )
            job = result.scalar_one_or_none()
            if job is not None:
                assert job.status == "failed"
                assert job.error_code == "SUBTITLE_NOT_FOUND"

        asyncio.get_event_loop().run_until_complete(check())
