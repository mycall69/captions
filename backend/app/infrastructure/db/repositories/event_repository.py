"""T097: SQLAlchemy 기반 JobEventRepository 구현.

job_event 테이블에 대한 INSERT / SELECT 연산을 제공한다.
event_type 허용 값: ``job.state_changed`` / ``job.progress`` / ``job.completed`` /
``job.failed`` / ``job.info`` (events.md §이벤트 타입).

SSE replay 시 ``id`` 컬럼(autoincrement) 을 ``Last-Event-ID`` 기준값으로 사용한다.
``seq`` 라는 별도 컬럼은 존재하지 않으며 ORM PK 가 그 역할을 겸한다
(events.md §공통 규칙).

세션은 호출자가 주입하며 본 저장소는 commit / rollback 을 수행하지 않는다 —
트랜잭션 경계는 ``JobEventPublisher`` 가 관리한다.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm import JobEvent

# events.md §공통 규칙 — replay 한도 50건
DEFAULT_REPLAY_LIMIT = 50


class JobEventRepository:
    """job_event 테이블 CRUD 저장소.

    모든 메서드는 비동기이며 외부에서 주입된 :class:`AsyncSession` 위에서 동작한다.
    """

    def __init__(self, session: AsyncSession) -> None:
        """세션을 보관한다 (publisher 와 동일 트랜잭션 공유)."""
        self._session = session

    async def append(
        self,
        *,
        job_id: str,
        event_type: str,
        payload: str,
    ) -> JobEvent:
        """새 이벤트 행을 추가하고 flush 한다 (commit 은 호출자가 수행).

        Args:
            job_id: 대상 VideoJob 의 26자 ULID.
            event_type: events.md §이벤트 타입의 5종 중 하나.
            payload: SSE push payload 와 동일 형식의 JSON 문자열.

        Returns:
            INSERT 된 :class:`JobEvent` ORM 인스턴스 (``id`` 가 채워진 상태).
        """
        row = JobEvent(job_id=job_id, event_type=event_type, payload=payload)
        self._session.add(row)
        # ``id`` autoincrement 값을 즉시 할당받기 위해 flush 한다.
        await self._session.flush()
        return row

    async def update_payload(self, row: JobEvent, payload: str) -> None:
        """flush 후 ``id`` 가 결정된 행의 payload 를 갱신한다.

        seq / event_id 를 payload JSON 안에 포함해야 하지만, seq 는 INSERT 후
        ORM PK 로 확정되므로 두 단계로 분리한다.
        """
        row.payload = payload
        await self._session.flush()

    async def list_after(
        self,
        job_id: str,
        *,
        after_seq: int = 0,
        limit: int = DEFAULT_REPLAY_LIMIT,
    ) -> list[JobEvent]:
        """``after_seq`` 보다 큰 id 의 이벤트를 오름차순으로 최대 limit 건 반환한다.

        SSE 재연결 시 ``Last-Event-ID`` 이후 누락분을 replay 하는 용도다.
        ``limit`` 은 events.md §공통 규칙의 50건 상한을 기본값으로 사용한다.
        """
        capped_limit = min(limit, DEFAULT_REPLAY_LIMIT)
        stmt = (
            select(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.id > after_seq)
            .order_by(JobEvent.id.asc())
            .limit(capped_limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars())

    async def get_max_seq(self, job_id: str) -> int:
        """해당 job 의 가장 큰 ``id`` 값을 반환한다 — 없으면 0."""
        stmt = select(func.max(JobEvent.id)).where(JobEvent.job_id == job_id)
        result = await self._session.execute(stmt)
        value = result.scalar_one_or_none()
        return int(value) if value is not None else 0


__all__ = ["JobEventRepository", "DEFAULT_REPLAY_LIMIT"]
