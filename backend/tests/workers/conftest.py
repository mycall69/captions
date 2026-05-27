"""워커 태스크 테스트 공통 fixture.

Celery 태스크가 사용하는 DB 세션을 테스트의 in-memory SQLite 세션으로 교체하여
태스크와 테스트가 동일한 데이터베이스를 바라보도록 설정한다.

StaticPool + check_same_thread=False: 새 스레드에서도 동일한 in-memory DB 접근 가능.
expire_on_commit=True: 커밋 후 세션 캐시를 비워 다른 세션의 변경이 반영되도록 한다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.infrastructure.db.orm import Base


@pytest_asyncio.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """워커 테스트용 in-memory SQLite 엔진.

    check_same_thread=False + StaticPool: 새 스레드(run_async 내부)에서도
    동일한 in-memory 데이터베이스에 접근할 수 있도록 설정한다.
    """
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """워커 테스트용 DB 세션.

    expire_on_commit=True: 커밋 후 식별 맵 내 객체를 만료시켜
    다른 세션(태스크)이 커밋한 변경 사항을 다음 쿼리에서 반영한다.
    """
    factory = async_sessionmaker(db_engine, expire_on_commit=True)
    async with factory() as session:
        yield session


@pytest.fixture(autouse=True)
def _patch_celery_eager(monkeypatch: pytest.MonkeyPatch) -> None:
    """Celery를 eager(동기) 모드로 실행한다 — 별도 worker 없이 인라인 실행.

    task_eager_propagates=False: retry 테스트에서 Celery가 예외를 직접 전파하지 않고
    retry 메커니즘이 정상 동작할 수 있도록 한다.
    예외가 필요한 테스트는 .apply(throw=True) 또는 pytest.raises로 명시적으로 처리한다.
    """
    from app.workers.celery_app import celery_app

    celery_app.conf.update(
        task_always_eager=True,
        task_eager_propagates=False,
    )


@pytest.fixture(autouse=True)
def _inject_session_factory(db_engine: AsyncEngine) -> Iterator[None]:
    """태스크 세션 팩토리를 in-memory DB 엔진 팩토리로 교체한다.

    run_async()가 새 스레드에서 실행되더라도 StaticPool을 통해
    동일한 in-memory SQLite 데이터베이스에 접근한다.
    expire_on_commit=False: 태스크 세션은 커밋 후에도 객체를 계속 사용한다.
    """
    from app.workers.tasks._runtime import set_session_factory_for_test

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    set_session_factory_for_test(factory)
    try:
        yield
    finally:
        set_session_factory_for_test(None)


@pytest_asyncio.fixture
async def translate_ready_job(db_session: AsyncSession) -> str:
    """번역 태스크 테스트용 픽스처 — subtitle_processing 상태의 작업 + source 트랙 + cue 30개.

    translate_task(job_id)를 실행하기 위해 필요한 최소 DB 상태를 구성한다:
    - VideoJob: subtitle_processing 상태, source_language=ja, target_language=ko
    - SubtitleTrack: source / ja / manual / vtt
    - SubtitleCue: 30개 (60s 윈도우 기준 복수 청크 생성 가능)
    """
    from app.core.ids import new_ulid
    from app.domain.jobs.models import VideoJob, VideoMetadata
    from app.domain.jobs.states import JobStatus
    from app.domain.subtitles.models import SubtitleCue, SubtitleTrack
    from app.infrastructure.db.repositories.job_repository import SqlJobRepository
    from app.infrastructure.db.repositories.subtitle_repository import SqlSubtitleRepository

    job_id = new_ulid()
    now = datetime.now(UTC)
    job = VideoJob(
        id=job_id,
        source_url="https://www.youtube.com/watch?v=abcdefghijk",
        youtube_video_id="abcdefghijk",
        source_language="ja",
        target_language="ko",
        status=JobStatus.subtitle_processing,
        metadata=VideoMetadata(
            title="테스트 영상",
            channel="테스트 채널",
            duration_sec=150,
            subtitle_source="manual",
        ),
        created_at=now,
        updated_at=now,
        reused=False,
    )
    jrepo = SqlJobRepository(db_session)
    await jrepo.create(job)

    srepo = SqlSubtitleRepository(db_session)
    # 30개 cue: 각 5초 간격 → 총 150초 → 60s 윈도우 기준 3개 청크 생성
    cues = [
        SubtitleCue(
            sequence=i + 1,
            start_ms=i * 5000,
            end_ms=i * 5000 + 4000,
            text=f"テスト字幕 {i + 1}",
        )
        for i in range(30)
    ]
    track = SubtitleTrack(
        id=new_ulid(),
        job_id=job_id,
        kind="source",
        language="ja",
        origin="manual",
        source_format="vtt",
        cue_count=len(cues),
        cues=cues,
    )
    await srepo.save_track(track)
    await db_session.commit()
    return job_id
