"""T093: 이벤트 발행 원자성 워커 테스트 (US2, FR-024, FR-026).

워커 태스크가 상태를 전이시키거나 진행률을 갱신할 때
`JobEventPublisher` 를 통해 다음 두 작업을 **원자적**으로 수행해야 한다.

1. `job_event` 테이블에 새 row INSERT (감사 / Last-Event-ID replay 용).
2. Redis Pub/Sub 채널(`job:{job_id}`) 에 동일 payload publish.

본 테스트는 events.md §백엔드 구현 메모(`상태 전이 + DB INSERT + publish` 트랜잭션)
를 다음 4개 사양으로 분해해 검증한다.

- 정상 경로: 두 부수효과(DB row + Redis publish) 가 동시에 성립한다.
- 실패 경로: Redis publish 가 실패하면 DB row 도 롤백되어야 한다 (둘 다 또는 둘 다 안 함).
- event_id 는 ULID 형식이며 발행 순서대로 단조 증가한다 (events.md §공통 규칙).
- seq 는 발행 순서대로 1씩 증가한다.

본 테스트는 RED 단계 — `app.domain.events.publisher` 구현(T099) 전까지 skip.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest

# T099 publisher 구현 전까지 import skip
pytest.importorskip(
    "app.domain.events.publisher",
    reason="awaiting T099 implementation — app.domain.events.publisher",
)

from app.domain.events.publisher import JobEventPublisher  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker  # noqa: E402

from app.core.ids import new_ulid  # noqa: E402
from app.domain.events.bus import EventBus, job_channel  # noqa: E402
from app.domain.jobs.models import VideoJob, VideoMetadata  # noqa: E402
from app.domain.jobs.states import JobStatus  # noqa: E402
from app.infrastructure.db.orm import JobEvent  # noqa: E402
from app.infrastructure.db.repositories.job_repository import SqlJobRepository  # noqa: E402

pytestmark = pytest.mark.workers


# ── 픽스처 ────────────────────────────────────────────────────────────────────

@pytest.fixture
async def seeded_job(db_session: AsyncSession) -> str:
    """publish 테스트용 작업 1건을 미리 생성해 job_id 를 반환한다."""
    now = datetime.now(UTC)
    job_id = new_ulid()
    job = VideoJob(
        id=job_id,
        source_url="https://www.youtube.com/watch?v=abcdefghijk",
        youtube_video_id="abcdefghijk",
        status=JobStatus.pending,
        metadata=VideoMetadata(
            title="이벤트 발행 테스트",
            channel="테스트 채널",
            duration_sec=120,
            subtitle_source="manual",
        ),
        created_at=now,
        updated_at=now,
        reused=False,
    )
    await SqlJobRepository(db_session).create(job)
    await db_session.commit()
    return job_id


@pytest.fixture
def fake_event_bus(fake_redis: Any) -> EventBus:
    """fakeredis 를 주입한 EventBus 인스턴스 — 실제 publish/subscribe 가능."""
    return EventBus.from_client(fake_redis)


# ── 보조 헬퍼 ────────────────────────────────────────────────────────────────


async def _publish_and_collect(
    bus: EventBus,
    channel: str,
    *,
    publisher: Callable[[], Awaitable[None]],
    n_expected: int,
    timeout: float = 1.0,
) -> list[dict[str, Any]]:
    """채널 구독 → publisher 실행 → 메시지 n_expected 개 수집 후 반환한다.

    asyncio.Event 로 subscribe 완료 시점을 확정해 race 를 제거한다.
    """
    ready = asyncio.Event()
    received: list[dict[str, Any]] = []

    async def _sub() -> None:
        async for payload in bus.subscribe(channel, ready=ready):
            received.append(payload)
            if len(received) >= n_expected:
                return

    task = asyncio.create_task(_sub())
    await ready.wait()
    await publisher()
    try:
        await asyncio.wait_for(task, timeout=timeout)
    except TimeoutError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    return received


# ── 1. 정상 경로: DB row + Redis publish 동시 성립 ──────────────────────────


class TestPublishHappyPath:
    """publish 가 성공하면 DB row 와 Redis 메시지가 모두 존재해야 한다."""

    async def test_publish_creates_db_row(
        self,
        db_session: AsyncSession,
        fake_event_bus: EventBus,
        seeded_job: str,
    ) -> None:
        """단일 발행 후 job_event 테이블에 row 가 1건 추가된다."""
        publisher = JobEventPublisher(session=db_session, bus=fake_event_bus)
        await publisher.publish_state_changed(
            job_id=seeded_job,
            previous_status=JobStatus.pending,
            new_status=JobStatus.downloading,
        )
        await db_session.commit()

        rows = (
            await db_session.execute(
                select(JobEvent).where(JobEvent.job_id == seeded_job)
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].event_type in {"state_changed", "job.state_changed"}

    async def test_publish_sends_redis_message(
        self,
        db_session: AsyncSession,
        fake_event_bus: EventBus,
        seeded_job: str,
    ) -> None:
        """publish 호출 시 Redis 채널에 메시지가 전달된다."""
        publisher = JobEventPublisher(session=db_session, bus=fake_event_bus)

        async def _do_publish() -> None:
            await publisher.publish_state_changed(
                job_id=seeded_job,
                previous_status=JobStatus.pending,
                new_status=JobStatus.downloading,
            )
            await db_session.commit()

        received = await _publish_and_collect(
            fake_event_bus,
            job_channel(seeded_job),
            publisher=_do_publish,
            n_expected=1,
            timeout=2.0,
        )

        assert len(received) == 1
        assert received[0].get("job_id") == seeded_job


# ── 2. 실패 경로: publish 실패 시 DB row 롤백 ───────────────────────────────


class TestPublishAtomicity:
    """Redis publish 가 실패하면 DB row 도 commit 되지 않아야 한다."""

    async def test_redis_failure_rolls_back_db_row(
        self,
        db_engine: AsyncEngine,
        db_session: AsyncSession,
        seeded_job: str,
    ) -> None:
        """publish 가 예외를 던지면 동일 트랜잭션의 INSERT 가 롤백되어야 한다.

        검증 전략:
        - publisher 호출 → 동일 엔진의 **별도 세션**에서 SELECT 한다.
          이렇게 하면 원본 세션의 in-flight INSERT 가 보이지 않으므로
          publisher 가 실제로 rollback 하지 않았다면 테스트가 실패한다.
        """

        class _ExplodingBus:
            async def publish(self, channel: str, payload: dict[str, Any]) -> None:  # noqa: ARG002
                raise RuntimeError("redis down")

            async def subscribe(  # noqa: ARG002
                self,
                channel: str,
                *,
                ready: asyncio.Event | None = None,
            ) -> Any:
                raise NotImplementedError

            async def close(self) -> None:  # pragma: no cover - 미사용 경로
                return None

        publisher = JobEventPublisher(session=db_session, bus=_ExplodingBus())

        with pytest.raises(RuntimeError, match="redis down"):
            await publisher.publish_state_changed(
                job_id=seeded_job,
                previous_status=JobStatus.pending,
                new_status=JobStatus.downloading,
            )

        # 동일 엔진에 묶인 **별도 세션**으로 조회 → in-flight pending INSERT 는 보이지 않는다.
        # publisher 가 실패 시 자체 rollback 을 수행했어야만 row 가 비어 있다.
        factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with factory() as verify_session:
            rows = (
                await verify_session.execute(
                    select(JobEvent).where(JobEvent.job_id == seeded_job)
                )
            ).scalars().all()
        assert rows == [], "publish 실패에도 불구하고 DB row 가 남아 있습니다."


# ── 3. event_id ULID 형식 + 단조 증가 ───────────────────────────────────────


class TestEventIdMonotonicity:
    """payload 의 event_id 는 ULID(26자) 이며 발행 순서대로 단조 증가한다."""

    async def test_event_id_is_ulid_format(
        self,
        db_session: AsyncSession,
        fake_event_bus: EventBus,
        seeded_job: str,
    ) -> None:
        """payload 의 event_id 는 26자 Crockford Base32 ULID 여야 한다."""
        publisher = JobEventPublisher(session=db_session, bus=fake_event_bus)

        async def _do_publish() -> None:
            await publisher.publish_state_changed(
                job_id=seeded_job,
                previous_status=JobStatus.pending,
                new_status=JobStatus.downloading,
            )
            await db_session.commit()

        received = await _publish_and_collect(
            fake_event_bus,
            job_channel(seeded_job),
            publisher=_do_publish,
            n_expected=1,
            timeout=2.0,
        )

        assert received
        event_id = received[0].get("event_id")
        assert isinstance(event_id, str)
        assert len(event_id) == 26, f"ULID 길이(26) 가 아님: {event_id!r}"
        # Crockford Base32 알파벳만 포함
        assert set(event_id).issubset(set("0123456789ABCDEFGHJKMNPQRSTVWXYZ"))

    async def test_event_id_monotonic_per_job(
        self,
        db_session: AsyncSession,
        fake_event_bus: EventBus,
        seeded_job: str,
    ) -> None:
        """동일 job 의 연속 publish 는 event_id 가 단조 증가해야 한다."""
        publisher = JobEventPublisher(session=db_session, bus=fake_event_bus)

        async def _do_publish() -> None:
            await publisher.publish_state_changed(
                job_id=seeded_job,
                previous_status=JobStatus.pending,
                new_status=JobStatus.downloading,
            )
            await publisher.publish_progress(
                job_id=seeded_job,
                status=JobStatus.downloading,
                progress=0.5,
            )
            await publisher.publish_state_changed(
                job_id=seeded_job,
                previous_status=JobStatus.downloading,
                new_status=JobStatus.subtitle_processing,
            )
            await db_session.commit()

        received = await _publish_and_collect(
            fake_event_bus,
            job_channel(seeded_job),
            publisher=_do_publish,
            n_expected=3,
            timeout=2.0,
        )

        # 3건 모두 수신해야 단조성 검증이 의미를 가진다. (0~1건이면 trivial pass)
        assert len(received) == 3, (
            f"3건 publish 후 수신된 이벤트가 {len(received)}건 — 단조성 검증 불가"
        )
        ids = [m["event_id"] for m in received]
        assert ids == sorted(ids), f"event_id 가 단조 증가하지 않음: {ids}"


# ── 4. seq 는 job 단위 단조 증가 ─────────────────────────────────────────────


class TestSeqMonotonicity:
    """payload.seq 는 job 단위로 1, 2, 3 ... 순차 증가한다."""

    async def test_seq_is_monotonically_increasing(
        self,
        db_session: AsyncSession,
        fake_event_bus: EventBus,
        seeded_job: str,
    ) -> None:
        """동일 job 에 대해 발행한 이벤트는 seq 가 단조 증가해야 한다."""
        publisher = JobEventPublisher(session=db_session, bus=fake_event_bus)

        async def _do_publish() -> None:
            await publisher.publish_state_changed(
                job_id=seeded_job,
                previous_status=JobStatus.pending,
                new_status=JobStatus.downloading,
            )
            await publisher.publish_progress(
                job_id=seeded_job,
                status=JobStatus.downloading,
                progress=0.25,
            )
            await publisher.publish_progress(
                job_id=seeded_job,
                status=JobStatus.downloading,
                progress=0.75,
            )
            await db_session.commit()

        received = await _publish_and_collect(
            fake_event_bus,
            job_channel(seeded_job),
            publisher=_do_publish,
            n_expected=3,
            timeout=2.0,
        )

        # 3건 모두 수신해야 단조성 검증이 의미를 가진다. (0~1건이면 trivial pass)
        assert len(received) == 3, (
            f"3건 publish 후 수신된 이벤트가 {len(received)}건 — 단조성 검증 불가"
        )
        seqs = [int(m["seq"]) for m in received]
        # 엄격한 단조 증가 — sorted + unique 동시 검증.
        assert seqs == sorted(set(seqs)), f"seq 가 엄격 단조 증가하지 않음: {seqs}"
