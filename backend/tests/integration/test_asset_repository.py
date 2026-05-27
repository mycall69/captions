"""T069: SqlVideoAssetRepository 통합 테스트.

in-memory SQLite db_session 위에서 자산 등록/조회 동작을 검증한다.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.domain.jobs.models import VideoJob, VideoMetadata
from app.domain.jobs.states import JobStatus
from app.infrastructure.db.repositories.asset_repository import SqlVideoAssetRepository
from app.infrastructure.db.repositories.job_repository import SqlJobRepository

pytestmark = pytest.mark.integration


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _jid(tag: str) -> str:
    """26자 테스트 job ID를 생성한다."""
    return f"01JASSETJOB{tag}".ljust(26, "0")[:26]


async def _create_job(job_repo: SqlJobRepository, job_id: str) -> None:
    """테스트용 VideoJob을 DB에 저장한다."""
    assert len(job_id) == 26
    now = datetime.now(tz=UTC)
    job = VideoJob(
        id=job_id,
        source_url="https://www.youtube.com/watch?v=dQw4w9WgXcY",  # type: ignore[arg-type]
        youtube_video_id="dQw4w9WgXcY",
        status=JobStatus.pending,
        metadata=VideoMetadata(),
        created_at=now,
        updated_at=now,
    )
    await job_repo.create(job)


# ── 테스트 클래스 ─────────────────────────────────────────────────────────────


class TestVideoAssetRepositoryRegister:
    """register 동작 검증."""

    async def test_register_inserts_row_and_returns_id(
        self, db_session, job_repo: SqlJobRepository, asset_repo: SqlVideoAssetRepository
    ) -> None:
        """register 호출 시 DB에 행이 삽입되고 유효한 id가 반환되어야 한다."""
        job_id = _jid("REG001")
        await _create_job(job_repo, job_id)

        asset_id = await asset_repo.register(
            job_id=job_id,
            kind="dual_srt",
            path=f"var/storage/{job_id}/dual.srt",
            mime_type="text/plain",
            byte_size=1024,
        )

        assert asset_id is not None
        assert len(asset_id) == 26

    async def test_register_multiple_assets_for_same_job(
        self, db_session, job_repo: SqlJobRepository, asset_repo: SqlVideoAssetRepository
    ) -> None:
        """동일 job에 여러 자산을 등록할 수 있어야 한다."""
        job_id = _jid("REG002")
        await _create_job(job_repo, job_id)

        id1 = await asset_repo.register(
            job_id=job_id,
            kind="dual_srt",
            path=f"var/storage/{job_id}/dual.srt",
            mime_type="text/plain",
            byte_size=1024,
        )
        id2 = await asset_repo.register(
            job_id=job_id,
            kind="dual_vtt",
            path=f"var/storage/{job_id}/dual.vtt",
            mime_type="text/vtt",
            byte_size=2048,
        )

        assert id1 != id2


class TestVideoAssetRepositoryListForJob:
    """list_for_job 동작 검증."""

    async def test_list_for_job_returns_all_assets(
        self, db_session, job_repo: SqlJobRepository, asset_repo: SqlVideoAssetRepository
    ) -> None:
        """list_for_job은 해당 job의 모든 자산을 반환해야 한다."""
        job_id = _jid("LIST001")
        await _create_job(job_repo, job_id)

        for kind, mime in [("dual_srt", "text/plain"), ("dual_vtt", "text/vtt")]:
            await asset_repo.register(
                job_id=job_id,
                kind=kind,
                path=f"var/storage/{job_id}/{kind}",
                mime_type=mime,
                byte_size=512,
            )

        assets = await asset_repo.list_for_job(job_id)

        assert len(assets) == 2
        kinds = {a.kind for a in assets}
        assert kinds == {"dual_srt", "dual_vtt"}

    async def test_list_for_job_returns_empty_when_no_assets(
        self, db_session, job_repo: SqlJobRepository, asset_repo: SqlVideoAssetRepository
    ) -> None:
        """자산이 없는 job에서 list_for_job 호출 시 빈 목록을 반환해야 한다."""
        job_id = _jid("LIST002")
        await _create_job(job_repo, job_id)

        assets = await asset_repo.list_for_job(job_id)

        assert assets == []

    async def test_list_for_job_does_not_return_other_jobs_assets(
        self, db_session, job_repo: SqlJobRepository, asset_repo: SqlVideoAssetRepository
    ) -> None:
        """다른 job의 자산이 포함되면 안 된다."""
        job_id_a = _jid("LIST003A")
        job_id_b = _jid("LIST003B")
        await _create_job(job_repo, job_id_a)
        await _create_job(job_repo, job_id_b)

        await asset_repo.register(
            job_id=job_id_a,
            kind="dual_srt",
            path=f"var/storage/{job_id_a}/dual.srt",
            mime_type="text/plain",
            byte_size=100,
        )

        assets_b = await asset_repo.list_for_job(job_id_b)

        assert assets_b == []


class TestVideoAssetRepositoryGet:
    """get 동작 검증."""

    async def test_get_returns_latest_asset_of_kind(
        self, db_session, job_repo: SqlJobRepository, asset_repo: SqlVideoAssetRepository
    ) -> None:
        """동일 kind의 자산이 여럿인 경우 가장 최신 것을 반환해야 한다."""
        job_id = _jid("GET001")
        await _create_job(job_repo, job_id)

        _id1 = await asset_repo.register(
            job_id=job_id,
            kind="dual_srt",
            path=f"var/storage/{job_id}/v1.srt",
            mime_type="text/plain",
            byte_size=500,
        )
        await asyncio.sleep(0.01)
        id2 = await asset_repo.register(
            job_id=job_id,
            kind="dual_srt",
            path=f"var/storage/{job_id}/v2.srt",
            mime_type="text/plain",
            byte_size=600,
        )

        latest = await asset_repo.get(job_id=job_id, kind="dual_srt")

        assert latest is not None
        assert latest.id == id2
        assert latest.byte_size == 600

    async def test_get_returns_none_when_not_found(
        self, db_session, job_repo: SqlJobRepository, asset_repo: SqlVideoAssetRepository
    ) -> None:
        """등록되지 않은 kind 조회 시 None을 반환해야 한다."""
        job_id = _jid("GET002")
        await _create_job(job_repo, job_id)

        result = await asset_repo.get(job_id=job_id, kind="thumbnail")

        assert result is None

    async def test_get_with_correct_fields(
        self, db_session, job_repo: SqlJobRepository, asset_repo: SqlVideoAssetRepository
    ) -> None:
        """get으로 반환된 VideoAsset의 모든 필드가 올바르게 매핑되어야 한다."""
        job_id = _jid("GET003")
        await _create_job(job_repo, job_id)

        asset_id = await asset_repo.register(
            job_id=job_id,
            kind="video_mp4",
            path=f"var/storage/{job_id}/output.mp4",
            mime_type="video/mp4",
            byte_size=99999,
        )

        asset = await asset_repo.get(job_id=job_id, kind="video_mp4")

        assert asset is not None
        assert asset.id == asset_id
        assert asset.job_id == job_id
        assert asset.kind == "video_mp4"
        assert asset.path == f"var/storage/{job_id}/output.mp4"
        assert asset.mime_type == "video/mp4"
        assert asset.byte_size == 99999
