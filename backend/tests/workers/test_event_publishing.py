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
from datetime import UTC, datetime
from typing import Any

import pytest

# T099 publisher 구현 전까지 import skip
pytest.importorskip(
    "app.domain.events.publisher",
    reason="awaiting T099 implementation — app.domain.events.publisher",
)

from app.domain.events.publisher import (
    JobEventPublisher,  # noqa: E402  # type: ignore[reportMissingImports]
)
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

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
    bus = EventBus.__new__(EventBus)
    bus._redis = fake_redis
    return bus


# ── 보조 헬퍼 ────────────────────────────────────────────────────────────────


async def _collect_one_publish(bus: EventBus, channel: str, timeout: float = 1.0) -> dict[str, Any]:
    """채널을 1회 구독해 첫 payload 1건을 수신해 반환한다 (타임아웃 시 빈 dict)."""
    received: list[dict[str, Any]] = []

    async def _sub() -> None:
        async for msg in bus.subscribe(channel):
            received.append(msg)
            break

    task = asyncio.create_task(_sub())
    await asyncio.sleep(0.05)  # 구독 준비 대기
    try:
        await asyncio.wait_for(task, timeout=timeout)
    except TimeoutError:
        task.cancel()
    return received[0] if received else {}


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
        channel = job_channel(seeded_job)

        # 구독 task 를 먼저 띄우고 publish 호출
        received: list[dict[str, Any]] = []

        async def _sub() -> None:
            async for msg in fake_event_bus.subscribe(channel):
                received.append(msg)
                break

        task = asyncio.create_task(_sub())
        await asyncio.sleep(0.05)

        await publisher.publish_state_changed(
            job_id=seeded_job,
            previous_status=JobStatus.pending,
            new_status=JobStatus.downloading,
        )
        await db_session.commit()

        try:
            await asyncio.wait_for(task, timeout=2.0)
        except TimeoutError:
            task.cancel()

        assert len(received) == 1
        assert received[0].get("job_id") == seeded_job


# ── 2. 실패 경로: publish 실패 시 DB row 롤백 ───────────────────────────────


class TestPublishAtomicity:
    """Redis publish 가 실패하면 DB row 도 commit 되지 않아야 한다."""

    async def test_redis_failure_rolls_back_db_row(
        self,
        db_session: AsyncSession,
        seeded_job: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """publish 가 예외를 던지면 동일 트랜잭션의 INSERT 가 롤백되어야 한다."""

        class _ExplodingBus:
            async def publish(self, channel: str, payload: dict[str, Any]) -> None:  # noqa: ARG002
                raise RuntimeError("redis down")

            async def subscribe(self, channel: str) -> Any:  # noqa: ARG002, ANN401
                raise NotImplementedError

            async def close(self) -> None:  # pragma: no cover - 미사용 경로
                return None

        publisher = JobEventPublisher(session=db_session, bus=_ExplodingBus())

        with pytest.raises(Exception):  # noqa: B017, BLE001
            await publisher.publish_state_changed(
                job_id=seeded_job,
                previous_status=JobStatus.pending,
                new_status=JobStatus.downloading,
            )

        # 새 세션으로 다시 조회하지 않더라도 동일 세션에서 rollback 되어야 함.
        await db_session.rollback()
        rows = (
            await db_session.execute(
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
        channel = job_channel(seeded_job)

        received: list[dict[str, Any]] = []

        async def _sub() -> None:
            async for msg in fake_event_bus.subscribe(channel):
                received.append(msg)
                break

        task = asyncio.create_task(_sub())
        await asyncio.sleep(0.05)

        await publisher.publish_state_changed(
            job_id=seeded_job,
            previous_status=JobStatus.pending,
            new_status=JobStatus.downloading,
        )
        await db_session.commit()

        try:
            await asyncio.wait_for(task, timeout=2.0)
        except TimeoutError:
            task.cancel()

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
        channel = job_channel(seeded_job)

        received: list[dict[str, Any]] = []

        async def _sub() -> None:
            async for msg in fake_event_bus.subscribe(channel):
                received.append(msg)
                if len(received) >= 3:
                    break

        task = asyncio.create_task(_sub())
        await asyncio.sleep(0.05)

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

        try:
            await asyncio.wait_for(task, timeout=2.0)
        except TimeoutError:
            task.cancel()

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
        channel = job_channel(seeded_job)

        received: list[dict[str, Any]] = []

        async def _sub() -> None:
            async for msg in fake_event_bus.subscribe(channel):
                received.append(msg)
                if len(received) >= 3:
                    break

        task = asyncio.create_task(_sub())
        await asyncio.sleep(0.05)

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

        try:
            await asyncio.wait_for(task, timeout=2.0)
        except TimeoutError:
            task.cancel()

        seqs = [int(m["seq"]) for m in received]
        assert seqs == sorted(seqs)
        # seq 사이 간격이 1 이라는 사양은 events.md 에 명시되지 않았으나, 단조성은 필수.
        assert len(set(seqs)) == len(seqs), f"seq 중복: {seqs}"
