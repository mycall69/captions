"""T092: SSE 컨트랙트 테스트 (US2, FR-024, FR-026).

`GET /v1/jobs/{job_id}/events` 엔드포인트 동작 검증
(contracts/events.md + contracts/openapi.yaml 기준).

검증 항목:
- 5종 이벤트 타입(`job.state_changed`, `job.progress`,
  `job.completed`, `job.failed`, `job.info`)을 정의대로 발행한다.
- 응답 Content-Type 은 `text/event-stream` 이다.
- 각 SSE 프레임은 `id:` / `event:` / `data:` 세 필드를 갖는다.
- `data` JSON 은 `job_id` 와 더불어 events.md 가 요구하는 필드를 포함한다.
- `Last-Event-ID` 헤더를 받으면 해당 id 초과의 이벤트만 replay 한다 (최대 50건).
- 30초 이상 idle 시 서버가 keepalive 코멘트(`: keepalive`) 프레임을 push 한다.
- 존재하지 않는 job_id 는 404 + NOT_FOUND 를 반환한다.

본 테스트는 RED 단계 — `app.api.v1.routes.events` 구현 전(=T101) 까지
모듈 import 실패로 전체 테스트가 skip 된다.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

# T101 SSE 라우터 구현 전까지 import skip 으로 RED 상태 유지
pytest.importorskip(
    "app.api.v1.routes.events",
    reason="awaiting T101 implementation — app.api.v1.routes.events",
)
pytest.importorskip(
    "app.main",
    reason="awaiting T101 implementation — events 라우터 배선",
)

from httpx import AsyncClient  # noqa: E402

from app.infrastructure.db.orm import JobEvent  # noqa: E402

pytestmark = pytest.mark.integration

# events.md 가 정의한 5종 이벤트 타입
_KNOWN_EVENT_TYPES = frozenset({
    "job.state_changed",
    "job.progress",
    "job.completed",
    "job.failed",
    "job.info",
})


def _parse_sse_frames(raw: str) -> list[dict[str, str]]:
    """SSE 텍스트 스트림을 프레임 dict 리스트로 파싱한다.

    각 프레임은 빈 줄(\\n\\n)로 구분된다. 코멘트 프레임(`:` 시작)은
    `{'_comment': ...}` 로 보존한다 — keepalive 검증에 사용.
    """
    frames: list[dict[str, str]] = []
    for block in raw.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        frame: dict[str, str] = {}
        for line in block.split("\n"):
            if line.startswith(":"):
                frame["_comment"] = line[1:].strip()
                continue
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            # SSE 스펙: ':' 다음 첫 한 칸은 무시
            if value.startswith(" "):
                value = value[1:]
            frame[key.strip()] = value
        if frame:
            frames.append(frame)
    return frames


async def _read_stream(client: AsyncClient, url: str, *, headers: dict[str, str] | None = None,
                       max_bytes: int = 16_384) -> str:
    """SSE 응답에서 max_bytes 까지 읽고 종료한다 (테스트 한정 헬퍼)."""
    async with client.stream("GET", url, headers=headers or {}) as resp:
        assert resp.status_code == 200, f"unexpected status: {resp.status_code}"
        assert resp.headers["content-type"].startswith("text/event-stream"), (
            f"unexpected content-type: {resp.headers['content-type']}"
        )
        buf = bytearray()
        async for chunk in resp.aiter_bytes():
            buf.extend(chunk)
            if len(buf) >= max_bytes:
                break
    return buf.decode("utf-8", errors="ignore")


@pytest.fixture
async def in_progress_job_id(client: AsyncClient, db_session: AsyncSession) -> str:
    """진행 중 작업을 하나 만들어 job_id 를 반환한다.

    엔드포인트는 ``job.progress`` 를 합성하지 않는다 (events.md §클라이언트 동작).
    실제 진행률 이벤트는 워커가 단계 진입 시 발행하므로, 컨트랙트 테스트가
    progress 페이로드를 검증할 수 있도록 fixture 에서 ``job_event`` 한 건을
    직접 시드한다 — replay 경로(``Last-Event-ID`` 또는 ``client.subscribe`` 시
    조회)로 SSE 스트림에 노출된다.
    """
    resp = await client.post(
        "/v1/jobs", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcY"}
    )
    assert resp.status_code in (200, 201)
    job_id: str = resp.json()["data"]["id"]

    # ``job.progress`` 한 건 시드 — FR-024 컨트랙트 검증용.
    db_session.add(
        JobEvent(
            job_id=job_id,
            event_type="job.progress",
            payload=json.dumps(
                {
                    "job_id": job_id,
                    "event_type": "job.progress",
                    "status": "pending",
                    "progress": 0.0,
                }
            ),
        )
    )
    await db_session.commit()
    return job_id


class TestSseContentType:
    """응답 헤더 / 미디어 타입 검증."""

    async def test_returns_text_event_stream_content_type(
        self, client: AsyncClient, in_progress_job_id: str
    ) -> None:
        """Content-Type 은 `text/event-stream` 이어야 한다 (charset 접미사 허용)."""
        async with client.stream("GET", f"/v1/jobs/{in_progress_job_id}/events") as resp:
            assert resp.status_code == 200
            ct = resp.headers.get("content-type", "")
            assert ct.startswith("text/event-stream"), f"unexpected content-type: {ct}"

    async def test_response_uses_cache_disabled_headers(
        self, client: AsyncClient, in_progress_job_id: str
    ) -> None:
        """캐시 / 프록시 버퍼링 방지 헤더(권장)를 검증한다 — 미지정이면 skip."""
        async with client.stream("GET", f"/v1/jobs/{in_progress_job_id}/events") as resp:
            cache = resp.headers.get("cache-control", "")
            if not cache:
                pytest.skip("Cache-Control 미지정 — 구현 단계에서 결정")
            assert "no-cache" in cache.lower() or "no-store" in cache.lower()


class TestSseFrameFormat:
    """프레임 형태(id / event / data) 검증."""

    async def test_each_frame_has_id_event_data_fields(
        self, client: AsyncClient, in_progress_job_id: str
    ) -> None:
        """발행된 모든 프레임은 id / event / data 세 필드를 가져야 한다."""
        raw = await _read_stream(client, f"/v1/jobs/{in_progress_job_id}/events")
        frames = [f for f in _parse_sse_frames(raw) if "_comment" not in f]
        assert frames, "수신한 이벤트 프레임이 없습니다."
        for frame in frames:
            assert "id" in frame, f"id 필드 누락: {frame!r}"
            assert "event" in frame, f"event 필드 누락: {frame!r}"
            assert "data" in frame, f"data 필드 누락: {frame!r}"

    async def test_event_type_is_one_of_five_known_types(
        self, client: AsyncClient, in_progress_job_id: str
    ) -> None:
        """`event` 필드 값은 events.md 가 정의한 5종 중 하나여야 한다."""
        raw = await _read_stream(client, f"/v1/jobs/{in_progress_job_id}/events")
        frames = [f for f in _parse_sse_frames(raw) if "_comment" not in f]
        assert frames, "수신한 이벤트 프레임이 없습니다."
        for frame in frames:
            assert frame["event"] in _KNOWN_EVENT_TYPES, (
                f"미정의 이벤트 타입: {frame['event']!r}"
            )

    async def test_data_field_is_valid_json(
        self, client: AsyncClient, in_progress_job_id: str
    ) -> None:
        """`data` 필드 본문은 JSON 으로 파싱 가능해야 한다."""
        raw = await _read_stream(client, f"/v1/jobs/{in_progress_job_id}/events")
        frames = [f for f in _parse_sse_frames(raw) if "_comment" not in f]
        assert frames, "수신한 이벤트 프레임이 없습니다."
        for frame in frames:
            payload = json.loads(frame["data"])
            assert isinstance(payload, dict)


class TestSseDataPayload:
    """data 본문이 events.md 가 요구하는 필드를 포함하는지 검증."""

    async def test_payload_includes_job_id(
        self, client: AsyncClient, in_progress_job_id: str
    ) -> None:
        """모든 payload 는 `job_id` 필드를 포함해야 한다."""
        raw = await _read_stream(client, f"/v1/jobs/{in_progress_job_id}/events")
        frames = [f for f in _parse_sse_frames(raw) if "_comment" not in f]
        assert frames
        for frame in frames:
            payload = json.loads(frame["data"])
            assert payload.get("job_id") == in_progress_job_id

    async def test_state_changed_payload_has_status_and_at(
        self, client: AsyncClient, in_progress_job_id: str
    ) -> None:
        """`job.state_changed` payload 는 status / at 필드를 포함한다.

        연결 직후 합성된 state_changed 가 한 건 발행되어야 한다 (events.md §클라이언트 동작).
        """
        raw = await _read_stream(client, f"/v1/jobs/{in_progress_job_id}/events")
        frames = [
            f for f in _parse_sse_frames(raw)
            if "_comment" not in f and f.get("event") == "job.state_changed"
        ]
        assert frames, "연결 직후 합성된 job.state_changed 가 없습니다."
        payload = json.loads(frames[0]["data"])
        assert "status" in payload
        assert "at" in payload

    async def test_progress_payload_has_progress_field(
        self, client: AsyncClient, in_progress_job_id: str
    ) -> None:
        """`job.progress` payload 는 0~1 범위의 progress 를 포함한다.

        진행률 이벤트는 워커가 단계 진입 시 발행하므로(events.md §클라이언트 동작),
        엔드포인트는 합성하지 않는다. fixture 가 시드한 ``job_event`` row 를
        ``Last-Event-ID=0`` replay 경로로 노출시켜 컨트랙트(FR-024)를 검증한다.
        """
        raw = await _read_stream(
            client,
            f"/v1/jobs/{in_progress_job_id}/events",
            headers={"Last-Event-ID": "0"},
        )
        progress_frames = [
            f for f in _parse_sse_frames(raw)
            if "_comment" not in f and f.get("event") == "job.progress"
        ]
        assert progress_frames, (
            "fixture 가 최소 1건의 job.progress 이벤트를 만들어야 합니다 (FR-024)."
        )
        for frame in progress_frames:
            payload = json.loads(frame["data"])
            assert "progress" in payload
            assert 0.0 <= float(payload["progress"]) <= 1.0


class TestSseLastEventIdReplay:
    """Last-Event-ID 헤더 → 누락 이벤트 replay 검증 (events.md §공통 규칙)."""

    async def test_last_event_id_replays_missed_events(
        self, client: AsyncClient, in_progress_job_id: str
    ) -> None:
        """Last-Event-ID 보다 큰 id 의 이벤트만 다시 수신해야 한다."""
        # 1) 일부 이벤트 수집
        raw1 = await _read_stream(client, f"/v1/jobs/{in_progress_job_id}/events")
        frames1 = [f for f in _parse_sse_frames(raw1) if "_comment" not in f]
        assert frames1, "첫 연결에서 이벤트가 수신되지 않았습니다."
        last_id = frames1[-1]["id"]

        # 2) Last-Event-ID 재연결 — 그 이후 id 만 수신되어야 함
        raw2 = await _read_stream(
            client,
            f"/v1/jobs/{in_progress_job_id}/events",
            headers={"Last-Event-ID": last_id},
        )
        frames2 = [f for f in _parse_sse_frames(raw2) if "_comment" not in f]
        for frame in frames2:
            assert int(frame["id"]) > int(last_id), (
                f"replay 가 last id 이하 이벤트를 다시 보냈습니다: {frame['id']} <= {last_id}"
            )

    async def test_replay_is_limited_to_50_events(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        in_progress_job_id: str,
    ) -> None:
        """replay 한도는 50건이다 — Last-Event-ID=0 으로 재연결 시 50건 초과 replay 금지.

        events.md §공통 규칙 "replay 한도 50건" 을 강제로 검증하기 위해
        DB 에 60건의 `job_event` 를 직접 시드한 뒤 Last-Event-ID=0 으로 재연결한다.
        구현이 51건 이상 replay 하면 어떤 카운트(60, 199, ...) 든 실패해야 한다.
        """
        try:
            from app.infrastructure.db.orm import JobEvent
        except ImportError:
            pytest.skip("JobEvent ORM 미구현 — replay 캡 검증 보류")

        # 1) 60건의 prior event 를 동일 job_id 로 시드한다.
        for i in range(1, 61):
            db_session.add(
                JobEvent(
                    job_id=in_progress_job_id,
                    event_type="job.progress",
                    payload=json.dumps(
                        {
                            "job_id": in_progress_job_id,
                            "seq": i,
                            "progress": i / 100.0,
                        }
                    ),
                )
            )
        await db_session.commit()

        # 2) Last-Event-ID=0 재연결 → replay 만 분리해 카운트한다.
        # `id:` 필드가 시드된 row id (정수) 인 프레임이 replay 프레임.
        # live (Redis pub/sub) 이벤트가 끼어드는 것을 막기 위해 한 번에 작게 읽고
        # 즉시 스트림을 끊는다. 그래도 keepalive 코멘트가 섞일 수 있으므로
        # `_comment` 프레임은 제외한다.
        # max_bytes 를 200_000 으로 잡아 60건 replay 가 모두 들어와도
        # 잘리지 않게 한다. 잘리면 캡 위반(51+ 건)을 감지할 수 없다.
        raw = await _read_stream(
            client,
            f"/v1/jobs/{in_progress_job_id}/events",
            headers={"Last-Event-ID": "0"},
            max_bytes=200_000,
        )
        all_frames = [f for f in _parse_sse_frames(raw) if "_comment" not in f]

        # replay 프레임만 식별: id 가 정수이며 시드한 60건의 id 범위 내인 프레임.
        # (라이브 합성 이벤트의 id 는 ULID/타임스탬프 기반으로 정수가 아닐 수 있음)
        replay_frames: list[dict[str, str]] = []
        for f in all_frames:
            fid = f.get("id", "")
            if fid.isdigit():
                replay_frames.append(f)

        # 하한 1: 실제로 replay 가 일어났음을 확인 (0건이면 검증 무의미).
        # 상한 50: events.md 명시 한도.
        assert 1 <= len(replay_frames) <= 50, (
            f"replay 한도(50) 위반 또는 0건: 시드 60건 중 {len(replay_frames)} 건 replay"
        )


class TestSseKeepalive:
    """30초 이상 idle 시 keepalive 코멘트 push 검증 (events.md §공통 규칙)."""

    async def test_keepalive_comment_is_sent_when_idle(
        self,
        client: AsyncClient,
        in_progress_job_id: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """idle 상태에서 `: keepalive` 형태의 코멘트 프레임이 푸시되어야 한다.

        실제 30초 대기는 비현실적이므로 짧은 keepalive 간격을 주입할 수 있는
        훅(`app.api.v1.routes.events.KEEPALIVE_INTERVAL_SEC`)을 monkeypatch 한다.
        해당 훅이 없으면 테스트를 skip 한다.
        """
        try:
            import app.api.v1.routes.events as _events_mod
        except ImportError:
            pytest.skip("events 라우터 미구현 — keepalive 검증 보류")

        if not hasattr(_events_mod, "KEEPALIVE_INTERVAL_SEC"):
            pytest.skip("KEEPALIVE_INTERVAL_SEC 훅 미정의 — T101 에서 노출 예정")

        monkeypatch.setattr(_events_mod, "KEEPALIVE_INTERVAL_SEC", 0.05)
        raw = await _read_stream(
            client, f"/v1/jobs/{in_progress_job_id}/events", max_bytes=4_096
        )

        # `:` 로 시작하는 코멘트 프레임이 한 건 이상 존재해야 한다.
        assert re.search(r"(?m)^:\s*keepalive", raw) is not None, (
            "keepalive 코멘트가 발견되지 않았습니다."
        )


class TestSseNotFound:
    """존재하지 않는 job_id 처리."""

    async def test_unknown_job_returns_404(self, client: AsyncClient) -> None:
        """존재하지 않는 job_id 로 SSE 연결 시 404 + NOT_FOUND."""
        fake_id = "00000000000000000000000000"  # 26자 ULID 형식
        resp = await client.get(f"/v1/jobs/{fake_id}/events")
        assert resp.status_code == 404
        body: dict[str, Any] = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "NOT_FOUND"
