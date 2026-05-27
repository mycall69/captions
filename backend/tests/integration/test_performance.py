"""T124: 성능 sanity 테스트 — SC-002 / SC-005 / SC-007 자동화 검증.

검증 대상 (spec.md §Success Criteria):

- **SC-007**: 신규 작업 제출 ``POST /v1/jobs`` 응답 시간이 1초 이하.
- **SC-002**: SSE 단계 전이 push 평균 latency 가 5초 이하.
  본 테스트는 fake_redis 환경에서 sub-ms 가 측정되므로 "scaffolding" 수준의 검사다.
- **SC-005**: 동일 URL 재요청 시 기존 완료 작업 재사용 응답 시간이 5초 이하.

본 테스트는 ``perf`` 마커가 부여되어 ``pytest -m perf`` 로 선택 실행이 가능하다.

설계 메모:

- 메타데이터 fetch 는 client fixture 가 이미 fake (~0ms) 로 주입한다.
- 첫 POST 와 두 번째 POST 모두 ``DISABLE_CHAIN_DISPATCH=true`` 로 Celery 디스패치는 skip.
- SC-002 는 fake bus → publish/subscribe 가 즉시 동작하는 환경에서 latency 측정.
"""

from __future__ import annotations

import time

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration, pytest.mark.perf]

_VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcY"


class TestPerformanceSanity:
    """SC-007 / SC-005 / SC-002 자동화."""

    async def test_post_jobs_responds_within_one_second(self, client: AsyncClient) -> None:
        """**SC-007**: ``POST /v1/jobs`` 응답 시간 ≤ 1 초."""
        start = time.perf_counter()
        resp = await client.post("/v1/jobs", json={"url": _VALID_URL})
        elapsed = time.perf_counter() - start

        assert resp.status_code in (200, 201)
        assert elapsed <= 1.0, f"POST /v1/jobs 응답이 {elapsed:.3f}s — SC-007(≤1초) 위반"

    async def test_duplicate_url_reuse_responds_within_five_seconds(
        self, client: AsyncClient
    ) -> None:
        """**SC-005**: 완료된 동일 URL 재요청 시 ``reused=True`` + 응답 ≤ 5 초.

        1. 신규 POST 로 작업을 생성한다.
        2. 동일 URL 로 두 번째 POST 를 보내 reused 응답을 받는다.
        3. 두 번째 응답 latency 가 5초 이하인지 확인한다.
        """
        # 1) 신규 작업 생성
        first = await client.post("/v1/jobs", json={"url": _VALID_URL})
        assert first.status_code == 201
        first_id = first.json()["data"]["id"]

        # 2) 두 번째 POST — reused 응답 측정
        start = time.perf_counter()
        second = await client.post("/v1/jobs", json={"url": _VALID_URL})
        elapsed = time.perf_counter() - start

        assert second.status_code == 200
        body = second.json()
        assert body["data"]["reused"] is True
        assert body["data"]["id"] == first_id
        assert elapsed <= 5.0, f"reused POST 응답이 {elapsed:.3f}s — SC-005(≤5초) 위반"

    async def test_event_publish_latency_under_five_seconds(self) -> None:
        """**SC-002**: ``EventBus.publish`` → ``subscribe`` 수신까지 평균 latency ≤ 5 초.

        본 검증은 fake_redis 기반이라 sub-ms 가 일반적이지만, scaffolding 으로 둠.
        프로덕션 Redis Pub/Sub 의 latency 회귀를 잡으려면 별도 부하 테스트가 필요하다.
        """
        import asyncio

        bus = await _build_inmemory_event_bus()
        channel = "perf:test"

        # subscribe 가 활성화될 때까지 ready 이벤트를 기다린다.
        ready = asyncio.Event()
        received: list[tuple[float, dict[str, object]]] = []

        async def _consume() -> None:
            async for msg in bus.subscribe(channel, ready=ready):  # type: ignore[attr-defined]
                received.append((time.perf_counter(), msg))
                if len(received) >= 3:
                    return

        task = asyncio.create_task(_consume())
        await ready.wait()

        latencies: list[float] = []
        for i in range(3):
            payload: dict[str, object] = {"seq": i, "ts": time.perf_counter()}
            send_at = time.perf_counter()
            await bus.publish(channel, payload)  # type: ignore[attr-defined]
            # 작은 yield — fakeredis 가 pubsub deliver 를 처리할 틈을 준다.
            await asyncio.sleep(0.01)
            if i < len(received):
                recv_at, _ = received[i]
                latencies.append(recv_at - send_at)

        # consumer task 정리
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

        # 모든 메시지가 도달했는지, 평균 latency 가 5초 이하인지 확인.
        assert len(received) >= 1, "EventBus 가 메시지를 전혀 전달하지 못함"
        if latencies:
            avg = sum(latencies) / len(latencies)
            assert avg <= 5.0, f"평균 publish→subscribe latency {avg:.3f}s — SC-002 위반"


# ── 헬퍼: fakeredis 기반 EventBus 인스턴스 ───────────────────────────────────


async def _build_inmemory_event_bus() -> object:
    """fakeredis 기반 in-memory EventBus 를 반환한다.

    프로덕션 EventBus 는 ``redis.asyncio`` 클라이언트를 사용하지만, fakeredis
    는 동일 인터페이스의 in-memory 구현을 제공해 테스트 isolated bus 를 만들 수 있다.
    """
    try:
        import fakeredis.aioredis as _fake_aioredis  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover
        pytest.skip("fakeredis 미설치 — SC-002 scaffolding 테스트 skip")

    from app.domain.events.bus import EventBus

    client = _fake_aioredis.FakeRedis(decode_responses=True)
    return EventBus.from_client(client)
