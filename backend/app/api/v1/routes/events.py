"""T101/T102: ``GET /v1/jobs/{job_id}/events`` SSE 엔드포인트.

contracts/events.md 가 정의한 5종 이벤트 스트림을 클라이언트에 푸시한다.

핵심 동작:

1. 연결 직후 현재 작업 상태를 한 번 합성해 push 한다 (``job.state_changed`` 만).
   events.md §클라이언트 동작 — 진행률은 워커가 단계 진입 시 발행하므로
   엔드포인트에서 ``job.progress`` 를 합성하지 않는다.
2. ``Last-Event-ID`` 헤더가 제공되면 ``JobEventRepository.list_after`` 로
   누락분을 오름차순으로 replay 한다 (최대 50건 — events.md §공통 규칙).
3. 이후 Redis Pub/Sub 채널(``job:{job_id}``) 구독으로 라이브 이벤트를 push 한다.
4. ``KEEPALIVE_INTERVAL_SEC`` 마다 ``: keepalive`` 코멘트 프레임을 보낸다.
   test seam: ``T092`` 의 keepalive 테스트가 monkeypatch 로 짧게 덮어쓴다.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.event import ServerSentEvent
from sse_starlette.sse import EventSourceResponse

from app.api.v1.dependencies import SubscribableBus, db_session, event_bus
from app.core.exceptions import NotFoundError
from app.core.ids import new_event_id
from app.domain.events.bus import job_channel
from app.domain.events.payloads import build_state_changed_event
from app.infrastructure.db.repositories.event_repository import (
    DEFAULT_REPLAY_LIMIT,
    JobEventRepository,
)
from app.infrastructure.db.repositories.job_repository import SqlJobRepository

# events.md §공통 규칙 — idle 30초 이상 시 keepalive 코멘트 push.
# 모듈 레벨 상수로 노출 — T092 keepalive 테스트가 monkeypatch 로 짧게 덮어쓴다.
KEEPALIVE_INTERVAL_SEC: float = 30.0

logger = logging.getLogger(__name__)

router = APIRouter()


def _parse_last_event_id(raw: str | None) -> int | None:
    """``Last-Event-ID`` 헤더 값을 정수 ``seq`` 로 파싱한다.

    형식이 올바르지 않거나 음수면 ``None`` 을 반환해 replay 를 건너뛴다.
    """
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    try:
        value = int(stripped)
    except ValueError:
        return None
    if value < 0:
        return None
    return value


def _payload_to_sse(payload: dict[str, Any]) -> ServerSentEvent:
    """publish payload(dict) → sse-starlette ServerSentEvent 변환.

    ``id`` 는 ``seq`` (monotonic int, job_event PK), ``event`` 는
    ``event_type`` 을 사용한다 (events.md §공통 규칙).

    구분자를 LF 로 고정 — events.md / 테스트 파서가 ``\n`` 기반이며
    sse-starlette 기본값(CRLF) 사용 시 값 뒤에 ``\r`` 이 남는다.
    """
    seq = payload.get("seq")
    event_type = payload.get("event_type") or "message"
    return ServerSentEvent(
        data=json.dumps(payload, ensure_ascii=False),
        event=str(event_type),
        id=str(seq) if seq is not None else None,
        sep="\n",
    )


@router.get("/jobs/{job_id}/events")
async def stream_job_events(
    job_id: str,
    request: Request,  # noqa: ARG001  # 추후 request_id 로깅 등에 사용
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    session: AsyncSession = Depends(db_session),  # noqa: B008
    bus: SubscribableBus = Depends(event_bus),  # noqa: B008
) -> EventSourceResponse:
    """``GET /v1/jobs/{job_id}/events`` — SSE 작업 이벤트 스트림.

    Returns:
        ``text/event-stream`` 응답. 연결 즉시 현재 상태를 합성 push 한 뒤
        라이브 Pub/Sub 이벤트를 push 한다.

    Raises:
        NotFoundError: 존재하지 않는 ``job_id`` → 404 + NOT_FOUND.
    """
    # 1) 존재 검증
    job_repo = SqlJobRepository(session)
    job = await job_repo.get(job_id)
    if job is None:
        raise NotFoundError(
            f"작업을 찾을 수 없습니다: {job_id}",
            details={"job_id": job_id},
        )

    after_seq = _parse_last_event_id(last_event_id)

    # 2) replay 분: SSE response 객체 생성 전에 미리 조회한다
    #    (이벤트 generator 내부에서 세션을 다시 사용해도 안전하지만,
    #     테스트 환경의 세션 lifecycle 단순화를 위해 동기 fetch).
    replay_events: list[Any] = []
    if after_seq is not None:
        event_repo = JobEventRepository(session)
        replay_events = await event_repo.list_after(
            job_id,
            after_seq=after_seq,
            limit=DEFAULT_REPLAY_LIMIT,
        )

    # 3) 합성 frame 생성 (연결 직후 push) — replay 가 없을 때만 적용
    #    Last-Event-ID 재연결 시에는 합성 state_changed 가 중복으로 보일 수 있으므로
    #    replay 이후 라이브 스트림 흐름을 유지한다.
    #
    #    seq=0 은 연결 시점 합성 sentinel 로 예약되어 있다 — 실제 ``job_event.id`` 는
    #    1 부터 시작(autoincrement)하므로 어떤 실제 이벤트와도 겹치지 않으며,
    #    Last-Event-ID 기반 replay 의 비교(``id > after_seq``) 대상에서 자연히 제외된다.
    synthesized: list[dict[str, Any]] = []
    if after_seq is None:
        status_value = job.status.value
        synthesized.append(
            build_state_changed_event(
                job_id=job_id,
                seq=0,  # 합성 sentinel — 실제 job_event.id (1+) 와 겹치지 않는다
                event_id=new_event_id(),
                previous_status=status_value,
                new_status=status_value,
            )
        )

    channel = job_channel(job_id)

    async def event_generator() -> AsyncGenerator[ServerSentEvent, None]:
        """SSE 본문 generator — replay → synthesized → live."""
        # (a) replay (오름차순)
        for row in replay_events:
            try:
                payload = json.loads(row.payload)
            except (json.JSONDecodeError, TypeError):
                # 손상된 payload 는 row.id 만 노출하고 본문을 빈 dict 로 대체
                payload = {"job_id": job_id, "seq": row.id, "event_type": row.event_type}
            payload.setdefault("seq", row.id)
            payload.setdefault("event_type", row.event_type)
            yield _payload_to_sse(payload)

        # (b) synthesized current-state frames
        for payload in synthesized:
            yield _payload_to_sse(payload)

        # (c) live Redis pub/sub — 별도 task 로 queue 로 옮긴 뒤 keepalive 와 다중화
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        ready = asyncio.Event()

        async def _consume() -> None:
            """bus.subscribe 의 메시지를 queue 로 전달하고 종료 시 None 을 push."""
            try:
                async for msg in bus.subscribe(channel, ready=ready):
                    await queue.put(msg)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("event.sse.subscribe_failed", extra={"job_id": job_id})
            finally:
                # 끝났음을 알리는 sentinel
                await queue.put(None)

        consumer_task = asyncio.create_task(_consume())
        try:
            # subscribe 가 실제로 활성화될 때까지 짧게 대기 (race 방지)
            with contextlib.suppress(TimeoutError):
                # ready 신호가 오지 않아도 계속 진행 (no-op bus 대비)
                await asyncio.wait_for(ready.wait(), timeout=1.0)

            while True:
                try:
                    msg = await asyncio.wait_for(
                        queue.get(),
                        timeout=KEEPALIVE_INTERVAL_SEC,
                    )
                except TimeoutError:
                    # idle keepalive — events.md §공통 규칙
                    yield ServerSentEvent(comment="keepalive", sep="\n")
                    continue

                if msg is None:
                    # 구독 generator 가 종료됨 — 더 이상 라이브 이벤트가 없음
                    break

                yield _payload_to_sse(msg)
        finally:
            consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await consumer_task

    headers = {
        "Cache-Control": "no-store",
        "X-Accel-Buffering": "no",
    }
    return EventSourceResponse(
        event_generator(),
        headers=headers,
        # sse-starlette 자체 ping 은 비활성화 — 커스텀 keepalive 로 대체.
        ping=600,
        # 줄 구분자를 LF 로 고정 — 테스트 파서가 '\n' 기준으로 분리하므로
        # 기본 CRLF 사용 시 값 뒤에 '\r' 이 남는 문제를 회피한다.
        sep="\n",
    )


__all__ = ["KEEPALIVE_INTERVAL_SEC", "router", "stream_job_events"]
