"""워커 태스크 공통 헬퍼 — 세션, 서비스, 비동기 실행기.

각 Celery 태스크는 동기 함수이므로 asyncio.run()으로 async 코드를 실행한다.
태스크 단위로 새 엔진과 세션을 생성하여 커넥션 풀 오염을 방지한다.

_SESSION_FACTORY_OVERRIDE: 테스트에서 주입용 in-memory 세션 팩토리를 설정할 수 있다.
None이면 settings.database_url을 사용한 새 엔진으로 세션을 생성한다.

_EVENT_BUS_OVERRIDE: 테스트에서 fakeredis 기반 EventBus 또는 stub 을 주입할 수 있다.
None 이면 settings.redis_url 로 새 EventBus 를 생성한다 (지연 연결).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.domain.events.bus import EventBus
from app.domain.events.publisher import BusLike, JobEventPublisher
from app.infrastructure.db.repositories.asset_repository import SqlVideoAssetRepository
from app.infrastructure.db.repositories.job_repository import SqlJobRepository
from app.infrastructure.db.repositories.subtitle_repository import SqlSubtitleRepository
from app.infrastructure.storage.filesystem import JobStorage

# 테스트 주입용 세션 팩토리 override — None 이면 settings.database_url 사용
_SESSION_FACTORY_OVERRIDE: async_sessionmaker[AsyncSession] | None = None

# 테스트 주입용 단일 세션 override — 팩토리 대신 고정 세션을 재사용할 때 사용
_SESSION_OVERRIDE: AsyncSession | None = None

# 테스트 주입용 EventBus override — None 이면 settings.redis_url 로 새로 생성
_EVENT_BUS_OVERRIDE: BusLike | None = None


def set_session_factory_for_test(factory: async_sessionmaker[AsyncSession] | None) -> None:
    """테스트에서 세션 팩토리를 주입한다.

    None으로 설정하면 기본(settings.database_url) 팩토리를 사용한다.
    """
    global _SESSION_FACTORY_OVERRIDE  # noqa: PLW0603
    _SESSION_FACTORY_OVERRIDE = factory


def set_session_for_test(session: AsyncSession | None) -> None:
    """테스트에서 단일 세션 인스턴스를 주입한다.

    설정된 경우 task_session()이 항상 이 세션을 반환한다.
    commit은 호출하지 않아 테스트의 트랜잭션을 그대로 유지한다.
    """
    global _SESSION_OVERRIDE  # noqa: PLW0603
    _SESSION_OVERRIDE = session


def run_async(coro: Awaitable[Any]) -> Any:
    """Celery 동기 태스크 안에서 async 코루틴을 실행한다.

    이미 실행 중인 이벤트 루프가 있는 경우(pytest-asyncio 환경 등)
    새 스레드 + 새 이벤트 루프에서 실행하여 중첩 방지.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # 실행 중인 루프 없음 — asyncio.run() 정상 사용
        return asyncio.run(coro)  # type: ignore[arg-type]

    # 이미 실행 중인 루프가 있는 경우 (pytest-asyncio 등) — 새 스레드에서 실행
    result_holder: list[Any] = []
    exc_holder: list[BaseException] = []

    def _run_in_thread() -> None:
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            result_holder.append(new_loop.run_until_complete(coro))
        except BaseException as e:  # noqa: BLE001
            exc_holder.append(e)
        finally:
            new_loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_in_thread)
        future.result()  # 완료 대기 (예외 재발생)

    if exc_holder:
        raise exc_holder[0]
    return result_holder[0]


@asynccontextmanager
async def task_session() -> AsyncIterator[AsyncSession]:
    """태스크 단위 세션 컨텍스트 매니저.

    우선순위:
    1. _SESSION_OVERRIDE가 설정된 경우 — 해당 세션을 그대로 반환 (commit 없음)
    2. _SESSION_FACTORY_OVERRIDE가 설정된 경우 — 해당 팩토리로 새 세션 생성
    3. 기본 — settings.database_url로 새 엔진 + 세션 생성
    """
    if _SESSION_OVERRIDE is not None:
        # 단일 세션 재사용: commit 없이 반환 (테스트 트랜잭션 유지)
        yield _SESSION_OVERRIDE
        return

    if _SESSION_FACTORY_OVERRIDE is not None:
        async with _SESSION_FACTORY_OVERRIDE() as session:
            yield session
            await session.commit()
        return

    from app.core.config import get_settings

    settings = get_settings()
    engine = create_async_engine(settings.database_url, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
            await session.commit()
    finally:
        await engine.dispose()


def storage() -> JobStorage:
    """JobStorage 인스턴스를 반환한다."""
    return JobStorage()


def jobs_repo(session: AsyncSession) -> SqlJobRepository:
    """AsyncSession으로 SqlJobRepository를 생성한다."""
    return SqlJobRepository(session)


def subtitle_repo(session: AsyncSession) -> SqlSubtitleRepository:
    """AsyncSession으로 SqlSubtitleRepository를 생성한다."""
    return SqlSubtitleRepository(session)


def asset_repo(session: AsyncSession) -> SqlVideoAssetRepository:
    """AsyncSession으로 SqlVideoAssetRepository를 생성한다."""
    return SqlVideoAssetRepository(session)


def set_event_bus_for_test(bus: BusLike | None) -> None:
    """테스트에서 EventBus stub 을 주입한다 (None 이면 기본 동작 복원)."""
    global _EVENT_BUS_OVERRIDE  # noqa: PLW0603
    _EVENT_BUS_OVERRIDE = bus


def _get_event_bus() -> BusLike:
    """현재 활성 EventBus 를 반환한다.

    테스트 override 가 설정돼 있으면 그 인스턴스를, 아니면 settings.redis_url 로
    새 EventBus 를 생성한다 (연결은 첫 publish 시 lazy 로 맺어진다).
    """
    if _EVENT_BUS_OVERRIDE is not None:
        return _EVENT_BUS_OVERRIDE

    from app.core.config import get_settings

    settings = get_settings()
    return EventBus(redis_url=settings.redis_url)


def event_publisher(session: AsyncSession) -> JobEventPublisher:
    """세션과 EventBus 로 :class:`JobEventPublisher` 를 생성한다."""
    return JobEventPublisher(session=session, bus=_get_event_bus())
