"""T025: Redis Pub/Sub 기반 이벤트 버스.

events.md의 채널 규칙(`job:{job_id}`)을 준수하며,
publish는 JSON 인코딩, subscribe는 JSON 디코딩 dict를 AsyncIterator로 제공한다.
FastAPI SSE 핸들러가 subscribe()를 소비하고, Celery task가 publish()를 호출한다.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as aioredis


def job_channel(job_id: str) -> str:
    """job_id에 대응하는 Redis Pub/Sub 채널 이름을 반환한다.

    events.md §발행 채널 규칙: ``job:{job_id}``.
    """
    return f"job:{job_id}"


class EventBus:
    """Redis Pub/Sub 래퍼 — 이벤트 발행 및 구독 원시 연산을 제공한다.

    사용 예::

        bus = EventBus(redis_url="redis://localhost:6379/0")
        await bus.publish(job_channel(job_id), {"event": "job.state_changed", ...})

        async for event in bus.subscribe(job_channel(job_id)):
            yield event  # SSE 핸들러로 전달

        await bus.close()
    """

    def __init__(self, redis_url: str) -> None:
        """Redis URL을 받아 클라이언트를 초기화한다.

        Args:
            redis_url: Redis 연결 URL (예: ``redis://localhost:6379/0``).
        """
        self._redis: aioredis.Redis[str] = aioredis.from_url(
            redis_url,
            decode_responses=True,
        )

    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        """채널에 JSON 인코딩된 payload를 발행한다.

        Args:
            channel: 발행 대상 채널 이름 (예: ``job:01HX2T...``).
            payload: 직렬화 가능한 dict 이벤트 payload.
        """
        await self._redis.publish(channel, json.dumps(payload, ensure_ascii=False))

    async def subscribe(self, channel: str) -> AsyncGenerator[dict[str, Any], None]:
        """채널을 구독하고 수신된 JSON dict를 순차로 yield한다.

        구독 해제는 호출자가 제너레이터를 종료(aclose 또는 break)함으로써 수행된다.

        Args:
            channel: 구독 대상 채널 이름 (예: ``job:01HX2T...``).

        Yields:
            수신 메시지를 JSON 디코딩한 dict.
        """
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for raw in pubsub.listen():
                # 타입 'subscribe' 확인 메시지는 건너뜀
                if raw["type"] != "message":
                    continue
                data = raw["data"]
                try:
                    yield json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    # 잘못된 JSON은 무시하고 계속 수신
                    continue
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()  # type: ignore[attr-defined]

    async def close(self) -> None:
        """Redis 연결을 닫는다. 앱 종료 시 호출해야 한다."""
        await self._redis.aclose()  # type: ignore[attr-defined]
