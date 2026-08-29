"""T130: SC-008 failure envelope coverage 테스트.

spec.md SC-008 ("실패한 작업 100건 중 사용자 친화적 사유가 노출된 비율 100%")을
자동화 검증한다. 6개 실패 시나리오 각각에 대해:

1. HTTP 응답 envelope 이 ``error.code`` / ``error.message`` (한국어, 빈 문자열 아님) /
   ``request_id`` 를 모두 포함하는지
2. DB ``video_job`` 행의 ``error_stage`` / ``error_message`` / ``error_code`` 컬럼이
   실패 시나리오에서 비어 있지 않은지 (워커 단계 실패 시나리오에 한함)

를 검증한다.

다루는 시나리오:

- ``INVALID_URL`` — POST /v1/jobs 잘못된 URL → 400 (envelope만)
- ``INVALID_INPUT`` — POST /v1/jobs 영상 길이 초과 → 400 (envelope만)
- ``SUBTITLE_NOT_FOUND`` — 워커 단계 실패 → GET /v1/jobs/{id} envelope + DB 컬럼
- ``DOWNLOAD_FAILED`` — 워커 단계 실패 → GET envelope + DB 컬럼
- ``TRANSLATION_FAILED`` — 워커 단계 실패 → GET envelope + DB 컬럼
- ``USER_CANCELLED`` — DELETE /v1/jobs/{id} → 200 envelope + GET envelope + DB 컬럼

워커 단계 실패는 실제 yt-dlp / Anthropic API 호출 없이 ``JobsService.mark_failed`` 를
직접 호출하여 시뮬레이션한다. 워커 task 코드(``app/workers/tasks/*``) 가
``mark_failed`` 를 호출하는 경로는 ``tests/workers/`` 에서 별도 검증된다.

본 모듈은 항상 활성화된다 (skip 없음).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs.service import JobsService
from app.domain.jobs.states import JobStatus
from app.infrastructure.db.orm import VideoJob as VideoJobOrm
from app.infrastructure.db.repositories.job_repository import SqlJobRepository

pytestmark = pytest.mark.integration

_VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcY"
_INVALID_URL = "https://example.com/not-youtube"

# request_id는 ULID(26자) 또는 UUID 형식(36자)을 모두 허용한다.
# (현 구현은 ULID — app.core.ids.new_request_id 참조)
_MIN_REQUEST_ID_LEN = 16


# ── 공통 헬퍼 ────────────────────────────────────────────────────────────────


def _assert_error_envelope(
    body: dict[str, object],
    *,
    expected_code: str,
) -> None:
    """응답 envelope 이 SC-008 요구를 만족하는지 검증한다.

    검증 항목:
    - ``success`` == False
    - ``error.code`` == 기대 코드
    - ``error.message`` 는 비어 있지 않은 문자열
    - ``request_id`` 는 비어 있지 않은 문자열 (ULID/UUID-shape)
    """
    assert body.get("success") is False, f"success != False: {body!r}"

    error = body.get("error")
    assert isinstance(error, dict), f"error 객체가 누락되었습니다: {body!r}"

    code = error.get("code")
    assert code == expected_code, f"error.code 불일치: expected={expected_code}, got={code!r}"

    message = error.get("message")
    assert isinstance(message, str), f"error.message 타입 오류: {type(message)}"
    assert message.strip(), "error.message 가 빈 문자열입니다 (SC-008 위반)"

    request_id = body.get("request_id")
    assert isinstance(request_id, str), f"request_id 타입 오류: {type(request_id)}"
    assert (
        len(request_id) >= _MIN_REQUEST_ID_LEN
    ), f"request_id 가 ULID/UUID-shape 이 아닙니다: {request_id!r}"


def _assert_success_envelope(body: dict[str, object]) -> None:
    """성공 envelope 의 공통 필드(``success`` / ``data`` / ``request_id``)를 검증한다."""
    assert body.get("success") is True, f"success != True: {body!r}"
    assert "data" in body, f"data 필드 누락: {body!r}"
    request_id = body.get("request_id")
    assert (
        isinstance(request_id, str) and len(request_id) >= _MIN_REQUEST_ID_LEN
    ), f"request_id 가 ULID/UUID-shape 이 아닙니다: {request_id!r}"


async def _assert_db_error_columns(
    db_session: AsyncSession,
    job_id: str,
    *,
    expected_code: str,
) -> None:
    """``video_job`` 행의 실패 컬럼이 모두 채워져 있는지 검증한다."""
    row = (
        await db_session.execute(select(VideoJobOrm).where(VideoJobOrm.id == job_id))
    ).scalar_one()

    assert row.status == JobStatus.failed.value, f"DB status 가 failed 가 아닙니다: {row.status!r}"
    assert (
        row.error_code == expected_code
    ), f"DB error_code 불일치: expected={expected_code}, got={row.error_code!r}"
    assert (
        isinstance(row.error_stage, str) and row.error_stage.strip()
    ), f"DB error_stage 가 비어 있습니다: {row.error_stage!r}"
    assert (
        isinstance(row.error_message, str) and row.error_message.strip()
    ), f"DB error_message 가 비어 있습니다 (SC-008 위반): {row.error_message!r}"


async def _create_job(client: AsyncClient) -> str:
    """공통 헬퍼: 새 작업을 생성하고 job_id 를 반환한다."""
    resp = await client.post("/v1/jobs", json={"url": _VALID_URL})
    assert resp.status_code in (200, 201), resp.text
    job_id = resp.json()["data"]["id"]
    assert isinstance(job_id, str)
    return job_id


def _make_service(db_session: AsyncSession) -> JobsService:
    """fake metadata fetcher 없이 repo 만 결합된 JobsService 인스턴스를 만든다.

    워커 단계 실패 시뮬레이션용 — ``mark_failed`` 만 호출하므로 metadata fetcher 는 호출되지 않는다.
    """
    return JobsService(SqlJobRepository(db_session))


# ── 1. INVALID_URL (POST 즉시 400) ────────────────────────────────────────────


class TestInvalidUrlEnvelope:
    """잘못된 URL → 400 INVALID_URL envelope 검증."""

    async def test_invalid_url_returns_envelope(self, client: AsyncClient) -> None:
        resp = await client.post("/v1/jobs", json={"url": _INVALID_URL})
        assert resp.status_code == 400
        _assert_error_envelope(resp.json(), expected_code="INVALID_URL")


# ── 2. INVALID_INPUT (영상 길이 초과 → 400) ──────────────────────────────────


class TestInvalidInputEnvelope:
    """영상 길이 초과 → 400 INVALID_INPUT envelope 검증."""

    async def test_video_too_long_returns_envelope(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import app.api.v1.routes.jobs as _routes

        async def _fake_fetch_duration(_url: str) -> int:
            return 7201  # 120분 + 1초

        monkeypatch.setattr(_routes, "fetch_video_duration", _fake_fetch_duration, raising=False)

        resp = await client.post("/v1/jobs", json={"url": _VALID_URL})
        assert resp.status_code == 400
        _assert_error_envelope(resp.json(), expected_code="INVALID_INPUT")


# ── 3. SUBTITLE_NOT_FOUND (워커 실패 시뮬레이션) ─────────────────────────────


class TestSubtitleNotFoundEnvelope:
    """워커 자막 추출 단계에서 manual / auto 모두 실패 → SUBTITLE_NOT_FOUND."""

    async def test_subtitle_not_found_envelope_and_db(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        job_id = await _create_job(client)

        # 워커가 마킹할 결과를 시뮬레이션한다.
        service = _make_service(db_session)
        await service.mark_failed(
            job_id,
            error_stage="subtitle_processing",
            error_code="SUBTITLE_NOT_FOUND",
            error_message="영상에서 자막을 찾을 수 없습니다",
        )
        await db_session.commit()

        # GET /v1/jobs/{id} 응답 envelope (성공 envelope — 실패 정보가 data 안에 포함됨)
        resp = await client.get(f"/v1/jobs/{job_id}")
        assert resp.status_code == 200
        body = resp.json()
        _assert_success_envelope(body)
        data = body["data"]
        assert data["status"] == JobStatus.failed.value
        assert data["error_code"] == "SUBTITLE_NOT_FOUND"
        assert isinstance(data["error_message"], str) and data["error_message"].strip()
        assert isinstance(data["error_stage"], str) and data["error_stage"].strip()

        await _assert_db_error_columns(db_session, job_id, expected_code="SUBTITLE_NOT_FOUND")


# ── 4. DOWNLOAD_FAILED (워커 실패 시뮬레이션) ────────────────────────────────


class TestDownloadFailedEnvelope:
    """워커 다운로드 단계 실패 → DOWNLOAD_FAILED.

    실제 yt-dlp 호출 실패는 ``tests/workers/test_download_task.py`` 에서 별도 검증한다.
    본 테스트는 mark_failed 호출 후 envelope / DB 컬럼만 검증한다.
    """

    async def test_download_failed_envelope_and_db(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        job_id = await _create_job(client)

        service = _make_service(db_session)
        await service.mark_failed(
            job_id,
            error_stage="downloading",
            error_code="DOWNLOAD_FAILED",
            error_message="영상 다운로드에 실패했습니다",
        )
        await db_session.commit()

        resp = await client.get(f"/v1/jobs/{job_id}")
        assert resp.status_code == 200
        body = resp.json()
        _assert_success_envelope(body)
        data = body["data"]
        assert data["status"] == JobStatus.failed.value
        assert data["error_code"] == "DOWNLOAD_FAILED"
        assert isinstance(data["error_message"], str) and data["error_message"].strip()
        assert isinstance(data["error_stage"], str) and data["error_stage"].strip()

        await _assert_db_error_columns(db_session, job_id, expected_code="DOWNLOAD_FAILED")


# ── 5. TRANSLATION_FAILED (워커 실패 시뮬레이션) ──────────────────────────────


class TestTranslationFailedEnvelope:
    """워커 번역 단계 실패 → TRANSLATION_FAILED.

    실제 Anthropic API 호출 실패는 ``tests/workers/test_translate_task.py`` 에서 별도 검증한다.
    """

    async def test_translation_failed_envelope_and_db(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        job_id = await _create_job(client)

        service = _make_service(db_session)
        await service.mark_failed(
            job_id,
            error_stage="translating",
            error_code="TRANSLATION_FAILED",
            error_message="번역 처리 중 오류가 발생했습니다",
        )
        await db_session.commit()

        resp = await client.get(f"/v1/jobs/{job_id}")
        assert resp.status_code == 200
        body = resp.json()
        _assert_success_envelope(body)
        data = body["data"]
        assert data["status"] == JobStatus.failed.value
        assert data["error_code"] == "TRANSLATION_FAILED"
        assert isinstance(data["error_message"], str) and data["error_message"].strip()
        assert isinstance(data["error_stage"], str) and data["error_stage"].strip()

        await _assert_db_error_columns(db_session, job_id, expected_code="TRANSLATION_FAILED")


# ── 6. USER_CANCELLED (DELETE) ──────────────────────────────────────────────


class TestUserCancelledEnvelope:
    """DELETE /v1/jobs/{id} → USER_CANCELLED envelope + DB 컬럼."""

    async def test_user_cancelled_envelope_and_db(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        job_id = await _create_job(client)

        # DELETE 응답 — 성공 envelope (취소가 정상 처리됨)
        delete_resp = await client.delete(f"/v1/jobs/{job_id}")
        assert delete_resp.status_code == 200, delete_resp.text
        _assert_success_envelope(delete_resp.json())

        # GET 응답 — 취소 후 작업 상태 / 에러 정보를 data 안에서 확인
        get_resp = await client.get(f"/v1/jobs/{job_id}")
        assert get_resp.status_code == 200
        body = get_resp.json()
        _assert_success_envelope(body)
        data = body["data"]
        assert data["status"] == JobStatus.failed.value
        assert data["error_code"] == "USER_CANCELLED"
        assert isinstance(data["error_message"], str) and data["error_message"].strip()
        assert isinstance(data["error_stage"], str) and data["error_stage"].strip()

        # DB session 을 갱신하기 위해 expire — DELETE 가 별도 세션을 사용했을 수 있음.
        await db_session.commit()
        await _assert_db_error_columns(db_session, job_id, expected_code="USER_CANCELLED")
