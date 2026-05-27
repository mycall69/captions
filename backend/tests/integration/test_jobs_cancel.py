"""T094: `DELETE /v1/jobs/{job_id}` cancel 컨트랙트 테스트
(US2, spec Clarifications Q3 / FR-028).

검증 항목:
- 진행 중(in-progress) 작업을 DELETE → 200 + status==failed,
  error_code==USER_CANCELLED 로 전이된다.
- 종결 상태(completed/failed) 작업을 DELETE → 409 + error.code
  ∈ {ILLEGAL_STATE, INVALID_STATE, JOB_NOT_READY} 를 반환한다.
- 존재하지 않는 job_id 를 DELETE → 404 + NOT_FOUND.
- 취소 확정 후 `var/storage/<job_id>/` 디렉터리는 완전히 삭제된다
  (storage_root 는 tmp_path 로 리다이렉트하여 검증).

본 테스트는 RED 단계 — `app.api.v1.routes.jobs.cancel_job` 구현(T103) 전까지
스킵된다. cancel 라우트 모듈이 별도가 아닌 jobs 라우터 확장(T103)이므로
훅 부재 시 skip 한다.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

pytest.importorskip(
    "app.api.v1.routes.jobs",
    reason="awaiting T103 implementation — DELETE /v1/jobs/{id}",
)
pytest.importorskip(
    "app.main",
    reason="awaiting T103 implementation — jobs cancel 라우터 배선",
)

# T103: DELETE handler 가 jobs 라우터에 노출되기 전까지 전체 모듈을 skip 한다.
# cancel_job / delete_job 중 어느 한 이름이라도 노출되면 활성화된다.
import app.api.v1.routes.jobs as _jobs_routes  # noqa: E402

if not any(
    hasattr(_jobs_routes, name) for name in ("cancel_job", "delete_job")
):
    pytest.skip(
        "awaiting T103 implementation — cancel_job 핸들러 미정의",
        allow_module_level=True,
    )

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.api.v1.dependencies import db_session as _real_db_session  # noqa: E402
from app.api.v1.dependencies import event_bus as _real_event_bus  # noqa: E402
from app.api.v1.dependencies import jobs_service as _real_jobs_service  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.domain.jobs.models import VideoMetadata  # noqa: E402
from app.domain.jobs.service import JobsService  # noqa: E402
from app.domain.jobs.states import JobStatus  # noqa: E402
from app.infrastructure.db.orm import JobEvent  # noqa: E402
from app.infrastructure.db.repositories.job_repository import SqlJobRepository  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402

pytestmark = pytest.mark.integration

# 종결 작업 cancel 시 허용되는 error code 후보
_TERMINAL_ERROR_CODES = frozenset({"ILLEGAL_STATE", "INVALID_STATE", "JOB_NOT_READY"})

_VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcY"


async def _fake_fetch_metadata(video_id: str) -> VideoMetadata:
    return VideoMetadata(
        title=f"Test Video {video_id}",
        channel="Test Channel",
        duration_sec=180,
        subtitle_source=None,
    )


# ── 픽스처: storage_root 를 tmp_path 로 리다이렉트한 client ─────────────────


@pytest_asyncio.fixture
async def cancel_client(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    """storage_root 가 tmp_path 인 통합 테스트 client.

    DELETE 후 디렉터리 삭제 검증을 위해 STORAGE_ROOT 환경변수를 tmp_path 로
    덮어쓰고 settings 캐시를 무효화한다. (monkeypatch 가 자동으로 원복)
    """
    # storage_root override — settings.storage_root 가 tmp_path 를 가리키게 함
    storage_root = tmp_path / "storage"
    storage_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("STORAGE_ROOT", str(storage_root))
    monkeypatch.setenv("DISABLE_CHAIN_DISPATCH", "true")
    get_settings.cache_clear()

    async def _override_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    def _override_jobs_service() -> JobsService:
        return JobsService(
            SqlJobRepository(db_session),
            metadata_fetcher=_fake_fetch_metadata,
        )

    # 취소 시 ``job.failed`` 를 publish 하므로 Redis 호출을 피하기 위해 no-op bus 주입.
    class _NoopBus:
        async def publish(self, channel: str, payload: dict[str, Any]) -> None:  # noqa: ARG002
            return None

    def _override_event_bus() -> object:
        return _NoopBus()

    fastapi_app.dependency_overrides[_real_db_session] = _override_db
    fastapi_app.dependency_overrides[_real_jobs_service] = _override_jobs_service
    fastapi_app.dependency_overrides[_real_event_bus] = _override_event_bus

    try:
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            yield c
    finally:
        fastapi_app.dependency_overrides.clear()
        get_settings.cache_clear()


async def _create_job(client: AsyncClient) -> str:
    """공통 헬퍼: 새 작업을 생성하고 job_id 를 반환한다."""
    resp = await client.post("/v1/jobs", json={"url": _VALID_URL})
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["data"]["id"]  # type: ignore[no-any-return]


async def _advance_status(db_session: AsyncSession, job_id: str, target: JobStatus) -> None:
    """테스트 도우미: 상태 머신을 따라 target 까지 단계적으로 전이시킨다."""
    repo = SqlJobRepository(db_session)
    sequence = [
        JobStatus.pending,
        JobStatus.downloading,
        JobStatus.subtitle_processing,
        JobStatus.translating,
        JobStatus.rendering,
        JobStatus.completed,
    ]
    if target not in sequence:
        raise ValueError(f"unsupported target status: {target}")
    target_index = sequence.index(target)
    for status in sequence[1 : target_index + 1]:
        await repo.update_status(job_id, status)
    await db_session.commit()


# ── 1. 진행 중 작업 취소 → USER_CANCELLED 로 failed 전이 ─────────────────────


class TestCancelInProgressJob:
    """진행 중 작업 cancel → state=failed + error_code=USER_CANCELLED."""

    async def test_cancel_pending_job_returns_200(
        self, cancel_client: AsyncClient
    ) -> None:
        """pending 작업 DELETE → 200 OK."""
        job_id = await _create_job(cancel_client)
        resp = await cancel_client.delete(f"/v1/jobs/{job_id}")
        assert resp.status_code == 200

    async def test_cancel_transitions_status_to_failed(
        self, cancel_client: AsyncClient
    ) -> None:
        """cancel 후 GET 으로 조회하면 status==failed 이어야 한다."""
        job_id = await _create_job(cancel_client)
        resp = await cancel_client.delete(f"/v1/jobs/{job_id}")
        assert resp.status_code == 200

        got = await cancel_client.get(f"/v1/jobs/{job_id}")
        assert got.status_code == 200
        data = got.json()["data"]
        assert data["status"] == "failed"

    async def test_cancel_sets_error_code_user_cancelled(
        self, cancel_client: AsyncClient
    ) -> None:
        """cancel 후 error_code 는 USER_CANCELLED 이다 (FR-028 / openapi ErrorBody)."""
        job_id = await _create_job(cancel_client)
        resp = await cancel_client.delete(f"/v1/jobs/{job_id}")
        body: dict[str, Any] = resp.json()
        data = body.get("data") or {}
        assert data.get("error_code") == "USER_CANCELLED"

    async def test_cancel_in_progress_downloading_job(
        self,
        cancel_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """downloading 단계의 작업도 동일하게 cancel 가능해야 한다."""
        job_id = await _create_job(cancel_client)
        await _advance_status(db_session, job_id, JobStatus.downloading)

        resp = await cancel_client.delete(f"/v1/jobs/{job_id}")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "failed"


# ── 2. 종결 작업 취소 → 409 ──────────────────────────────────────────────────


class TestCancelTerminalJobReturns409:
    """completed / failed 작업 cancel → 409."""

    async def test_completed_job_cancel_returns_409(
        self,
        cancel_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """completed 작업 DELETE → 409."""
        job_id = await _create_job(cancel_client)
        await _advance_status(db_session, job_id, JobStatus.completed)

        resp = await cancel_client.delete(f"/v1/jobs/{job_id}")
        assert resp.status_code == 409

    async def test_completed_job_cancel_error_code_is_illegal_state(
        self,
        cancel_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """409 응답의 error.code 는 ILLEGAL_STATE / INVALID_STATE / JOB_NOT_READY 중 하나."""
        job_id = await _create_job(cancel_client)
        await _advance_status(db_session, job_id, JobStatus.completed)

        resp = await cancel_client.delete(f"/v1/jobs/{job_id}")
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] in _TERMINAL_ERROR_CODES, (
            f"unexpected error code: {body['error']['code']}"
        )

    async def test_already_failed_job_cancel_returns_409(
        self,
        cancel_client: AsyncClient,
    ) -> None:
        """failed 상태에서 또 cancel 시도 시 409 — 이중 취소 방지."""
        job_id = await _create_job(cancel_client)

        # 첫 번째 cancel
        first = await cancel_client.delete(f"/v1/jobs/{job_id}")
        assert first.status_code == 200

        # 두 번째 cancel 은 409
        second = await cancel_client.delete(f"/v1/jobs/{job_id}")
        assert second.status_code == 409
        assert second.json()["error"]["code"] in _TERMINAL_ERROR_CODES


# ── 3. 존재하지 않는 작업 ─────────────────────────────────────────────────────


class TestCancelMissingJobReturns404:
    """존재하지 않는 job_id cancel → 404 + NOT_FOUND."""

    async def test_unknown_id_returns_404(self, cancel_client: AsyncClient) -> None:
        fake_id = "00000000000000000000000000"  # 26자 ULID 형식
        resp = await cancel_client.delete(f"/v1/jobs/{fake_id}")
        assert resp.status_code == 404
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "NOT_FOUND"


# ── 4. 취소 후 var/storage/<job_id>/ 디렉터리 purge ──────────────────────────


class TestCancelPurgesJobStorage:
    """취소 확정 후 부분 산출물(`var/storage/<job_id>/`) 이 완전 삭제되어야 한다.

    spec Clarifications Q3 / FR-028 / tasks.md T103 본문 참조.
    """

    async def test_storage_directory_is_purged_after_cancel(
        self,
        cancel_client: AsyncClient,
        tmp_path: Path,
    ) -> None:
        """DELETE 후 storage_root/<job_id> 디렉터리가 더 이상 존재하지 않아야 한다."""
        job_id = await _create_job(cancel_client)
        storage_root = tmp_path / "storage"
        job_dir = storage_root / job_id

        # 다운로드 단계가 일부라도 진행됐다고 가정 — 더미 파일을 미리 생성
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "video.mp4.part").write_bytes(b"partial download")
        assert job_dir.exists()

        resp = await cancel_client.delete(f"/v1/jobs/{job_id}")
        assert resp.status_code == 200, resp.text

        # 디렉터리 자체가 사라져야 한다 (purge_job_directory 호출 확인)
        assert not job_dir.exists(), (
            f"취소 후에도 디렉터리가 남아 있습니다: {job_dir}"
        )


# ── 5. 취소 시 job.failed 이벤트 발행 ────────────────────────────────────────


class TestCancelPublishesFailedEvent:
    """취소 확정 후 ``job.failed`` SSE 이벤트가 발행되어야 한다.

    events.md §이벤트 타입 + Last-Event-ID replay 경로로 클라이언트가 종결을
    학습하기 위해 필요하다 (SSE 구독 중이지 않더라도 재연결 시 따라잡을 수 있어야 함).
    """

    async def test_cancel_writes_job_failed_event_with_user_cancelled(
        self,
        cancel_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """DELETE 후 ``job_event`` 테이블에 ``job.failed`` row 가 기록되며,
        payload 의 ``error_code`` 는 ``USER_CANCELLED`` 다.
        """
        job_id = await _create_job(cancel_client)

        resp = await cancel_client.delete(f"/v1/jobs/{job_id}")
        assert resp.status_code == 200, resp.text

        # job_event 테이블에서 해당 job 의 job.failed row 를 조회한다.
        stmt = (
            select(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.event_type == "job.failed")
            .order_by(JobEvent.id.asc())
        )
        rows = (await db_session.execute(stmt)).scalars().all()
        assert rows, "취소 후 job.failed 이벤트가 기록되지 않았습니다."

        payload = json.loads(rows[-1].payload)
        assert payload.get("error_code") == "USER_CANCELLED"
        assert payload.get("error_stage") == "user"
        assert payload.get("job_id") == job_id
