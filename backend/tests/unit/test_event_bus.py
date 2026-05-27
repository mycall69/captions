"""T025 단위 테스트: Redis 이벤트 버스.

fakeredis.aioredis.FakeRedis를 사용해 실제 Redis 없이 publish/subscribe를 검증한다.
"""

from __future__ import annotations

import asyncio

import pytest

from app.domain.events.bus import EventBus, job_channel


class TestJobChannel:
    """job_channel 채널 이름 생성 함수 검증."""

    def test_channel_format(self) -> None:
        """job_channel은 'job:{job_id}' 형식을 반환해야 한다."""
        assert job_channel("01HX2TXXXXXXXXXXXXXXXX") == "job:01HX2TXXXXXXXXXXXXXXXX"

    def test_channel_with_simple_id(self) -> None:
        assert job_channel("abc") == "job:abc"

    def test_channel_different_ids_produce_different_channels(self) -> None:
        assert job_channel("id1") != job_channel("id2")


class TestEventBus:
    """EventBus publish / subscribe 검증 — fakeredis 사용."""

    @pytest.mark.asyncio
    async def test_publish_and_subscribe_roundtrip(self) -> None:
        """publish한 dict를 subscribe에서 동일하게 수신해야 한다."""
        import fakeredis
        from fakeredis.aioredis import FakeRedis

        fake_server = fakeredis.FakeServer()
        bus = EventBus.__new__(EventBus)
        bus._redis = FakeRedis(server=fake_server, decode_responses=True)

        channel = job_channel("test-job-001")
        payload = {"event": "job.state_changed", "status": "downloading"}

        received: list[dict] = []

        async def _subscriber() -> None:
            async for msg in bus.subscribe(channel):
                received.append(msg)
                break  # 첫 메시지만 수신 후 종료

        subscriber_task = asyncio.create_task(_subscriber())

        # 구독이 준비될 때까지 짧게 대기
        await asyncio.sleep(0.05)

        await bus.publish(channel, payload)

        try:
            await asyncio.wait_for(subscriber_task, timeout=2.0)
        except TimeoutError:
            subscriber_task.cancel()

        assert len(received) == 1
        assert received[0] == payload

        await bus.close()

    @pytest.mark.asyncio
    async def test_publish_encodes_korean_text(self) -> None:
        """한국어 텍스트가 포함된 payload도 올바르게 인코딩·디코딩되어야 한다."""
        from fakeredis.aioredis import FakeRedis

        bus = EventBus.__new__(EventBus)
        bus._redis = FakeRedis(decode_responses=True)

        channel = job_channel("korean-test")
        payload = {
            "event": "job.failed",
            "error_message": "이 영상에는 한국어 / 일본어 자막이 없습니다.",
        }

        received: list[dict] = []

        async def _sub() -> None:
            async for msg in bus.subscribe(channel):
                received.append(msg)
                break

        task = asyncio.create_task(_sub())
        await asyncio.sleep(0.05)
        await bus.publish(channel, payload)

        try:
            await asyncio.wait_for(task, timeout=2.0)
        except TimeoutError:
            task.cancel()

        assert len(received) == 1
        assert received[0]["error_message"] == "이 영상에는 한국어 / 일본어 자막이 없습니다."

        await bus.close()

    @pytest.mark.asyncio
    async def test_non_message_types_are_skipped(self) -> None:
        """subscribe/unsubscribe 확인 메시지는 yield되지 않아야 한다.

        FakeRedis는 subscribe 시 type='subscribe' 메시지를 emit하므로
        이것이 dict로 yield되지 않는지 확인한다.
        """
        from fakeredis.aioredis import FakeRedis

        bus = EventBus.__new__(EventBus)
        bus._redis = FakeRedis(decode_responses=True)

        channel = job_channel("skip-test")
        real_payload = {"event": "job.progress", "progress": 0.5}

        received: list[dict] = []

        async def _sub() -> None:
            async for msg in bus.subscribe(channel):
                received.append(msg)
                break

        task = asyncio.create_task(_sub())
        await asyncio.sleep(0.05)
        await bus.publish(channel, real_payload)

        try:
            await asyncio.wait_for(task, timeout=2.0)
        except TimeoutError:
            task.cancel()

        # 수신된 메시지 중 실제 payload만 있어야 함
        assert all(msg.get("event") == "job.progress" for msg in received)

        await bus.close()
