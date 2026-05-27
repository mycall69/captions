"""T099: 작업 이벤트 트랜잭션 발행기.

events.md §백엔드 구현 메모 — "상태 전이 + DB INSERT + publish 를 트랜잭션으로 묶는다".

본 모듈은 SSE 이벤트를 다음 순서로 원자적으로 발행한다.

1. ``job_event`` 테이블에 새 row 를 INSERT 후 flush (id 즉시 확정).
2. ``id`` 를 ``seq`` 로 사용한 payload 를 row.payload 에 다시 저장 + flush.
3. Redis Pub/Sub 채널(``job:{job_id}``) 에 동일 payload publish.
4. publish 가 실패하면 세션 rollback 후 예외 재발생 — DB row 도 함께 폐기된다.

호출자는 publish 가 모두 성공한 뒤 ``session.commit()`` 을 명시적으로 호출한다.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_event_id
from app.domain.events.bus import job_channel
from app.domain.events.payloads import (
    build_completed_event,
    build_failed_event,
    build_info_event,
    build_progress_event,
    build_state_changed_event,
)
from app.domain.jobs.states import JobStatus
from app.infrastructure.db.orm import JobEvent
from app.infrastructure.db.repositories.event_repository import JobEventRepository

logger = structlog.get_logger(__name__)


class BusLike(Protocol):
    """발행 대상 Bus 의 최소 인터페이스 (테스트 stub 도 적합)."""

    async def publish(self, channel: str, payload: dict[str, Any]) -> None: ...


class JobEventPublisher:
    """단일 세션 + Bus 조합으로 이벤트 발행 트랜잭션을 캡슐화한다.

    Lifecycle::

        publisher = JobEventPublisher(session=session, bus=bus)
        await publisher.publish_state_changed(...)
        await publisher.publish_progress(...)
        await session.commit()  # 호출자가 명시적으로 commit

    publish 가 예외를 던지면 자체적으로 ``session.rollback()`` 을 호출한 뒤
    원본 예외를 재발생시킨다 — DB row 와 Redis 메시지의 atomicity 를 보장한다.
    """

    def __init__(self, *, session: AsyncSession, bus: BusLike) -> None:
        """세션과 Bus 를 주입한다."""
        self._session = session
        self._bus = bus
        self._repo = JobEventRepository(session)

    # ── 공개 API ─────────────────────────────────────────────────────────────

    async def publish_state_changed(
        self,
        *,
        job_id: str,
        previous_status: JobStatus | str,
        new_status: JobStatus | str,
    ) -> JobEvent:
        """``job.state_changed`` 이벤트를 발행한다."""
        prev = previous_status.value if isinstance(previous_status, JobStatus) else previous_status
        new = new_status.value if isinstance(new_status, JobStatus) else new_status

        def builder(*, seq: int, event_id: str) -> dict[str, Any]:
            return build_state_changed_event(
                job_id=job_id,
                seq=seq,
                event_id=event_id,
                previous_status=prev,
                new_status=new,
            )

        return await self._publish(
            job_id=job_id,
            event_type="job.state_changed",
            builder=builder,
        )

    async def publish_progress(
        self,
        *,
        job_id: str,
        status: JobStatus | str,
        progress: float,
        detail: dict[str, Any] | None = None,
    ) -> JobEvent:
        """``job.progress`` 이벤트를 발행한다."""
        stage = status.value if isinstance(status, JobStatus) else status

        def builder(*, seq: int, event_id: str) -> dict[str, Any]:
            return build_progress_event(
                job_id=job_id,
                seq=seq,
                event_id=event_id,
                status=stage,
                progress=progress,
                detail=detail,
            )

        return await self._publish(
            job_id=job_id,
            event_type="job.progress",
            builder=builder,
        )

    async def publish_completed(
        self,
        *,
        job_id: str,
        assets: dict[str, str] | None = None,
        completed_at: str | None = None,
    ) -> JobEvent:
        """``job.completed`` 이벤트를 발행한다."""

        def builder(*, seq: int, event_id: str) -> dict[str, Any]:
            return build_completed_event(
                job_id=job_id,
                seq=seq,
                event_id=event_id,
                assets=assets,
                completed_at=completed_at,
            )

        return await self._publish(
            job_id=job_id,
            event_type="job.completed",
            builder=builder,
        )

    async def publish_failed(
        self,
        *,
        job_id: str,
        error_stage: str,
        error_code: str,
        error_message: str,
    ) -> JobEvent:
        """``job.failed`` 이벤트를 발행한다."""

        def builder(*, seq: int, event_id: str) -> dict[str, Any]:
            return build_failed_event(
                job_id=job_id,
                seq=seq,
                event_id=event_id,
                error_stage=error_stage,
                error_code=error_code,
                error_message=error_message,
            )

        return await self._publish(
            job_id=job_id,
            event_type="job.failed",
            builder=builder,
        )

    async def publish_info(
        self,
        *,
        job_id: str,
        code: str,
        message: str,
    ) -> JobEvent:
        """``job.info`` 이벤트를 발행한다."""

        def builder(*, seq: int, event_id: str) -> dict[str, Any]:
            return build_info_event(
                job_id=job_id,
                seq=seq,
                event_id=event_id,
                code=code,
                message=message,
            )

        return await self._publish(
            job_id=job_id,
            event_type="job.info",
            builder=builder,
        )

    # ── 내부 구현 ────────────────────────────────────────────────────────────

    async def _publish(
        self,
        *,
        job_id: str,
        event_type: str,
        builder: Any,
    ) -> JobEvent:
        """이벤트 row 를 INSERT → payload 갱신 → Redis publish 순서로 발행한다.

        publish 단계에서 예외가 발생하면 세션을 rollback 한 뒤 원본 예외를
        재발생시킨다 (atomicity 보장 — events.md §백엔드 구현 메모).
        """
        # 1) 행 reserve → id (= seq) 확정
        row = await self._repo.append(
            job_id=job_id,
            event_type=event_type,
            payload="{}",
        )

        # 2) seq / event_id 가 포함된 최종 payload 를 만들어 row 에 저장
        event_id = new_event_id()
        payload = builder(seq=row.id, event_id=event_id)
        await self._repo.update_payload(row, json.dumps(payload, ensure_ascii=False))

        # 3) Redis 채널 publish — 실패 시 rollback + re-raise
        try:
            await self._bus.publish(job_channel(job_id), payload)
        except BaseException:
            # ``session.rollback()`` 은 1)+2) 의 flush 된 INSERT 를 모두 폐기한다.
            await self._session.rollback()
            logger.warning(
                "event.publish_failed_rolled_back",
                job_id=job_id,
                event_type=event_type,
            )
            raise

        logger.debug(
            "event.published",
            job_id=job_id,
            event_type=event_type,
            seq=row.id,
            event_id=event_id,
        )
        return row


__all__ = ["BusLike", "JobEventPublisher"]
