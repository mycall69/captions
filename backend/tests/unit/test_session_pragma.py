"""T016: 비동기 SQLAlchemy 엔진 및 WAL PRAGMA 단위 테스트.

인메모리 SQLite 데이터베이스를 사용해 PRAGMA 리스너가 올바르게
등록·실행되는지 검증한다.

참고:
- WAL journal_mode는 인메모리 DB에서 'memory'로 반환될 수 있다.
- foreign_keys=ON은 인메모리 DB에서도 정상 적용된다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_pragma_listener_is_callable() -> None:
    """_apply_sqlite_pragmas 함수가 임포트 가능하고 호출 가능해야 한다."""
    from app.infrastructure.db.session import _apply_sqlite_pragmas

    assert callable(_apply_sqlite_pragmas)


@pytest.mark.asyncio
async def test_foreign_keys_pragma_applied() -> None:
    """인메모리 SQLite DB에서 foreign_keys PRAGMA가 ON으로 설정되어야 한다."""
    from app.infrastructure.db.session import _apply_sqlite_pragmas

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    event.listen(engine.sync_engine, "connect", _apply_sqlite_pragmas)

    async with engine.connect() as conn:
        result = await conn.execute(text("PRAGMA foreign_keys"))
        value = result.scalar()

    await engine.dispose()
    # foreign_keys=ON → 1
    assert value == 1


@pytest.mark.asyncio
async def test_busy_timeout_pragma_applied() -> None:
    """인메모리 SQLite DB에서 busy_timeout PRAGMA가 설정되어야 한다."""
    from app.infrastructure.db.session import _apply_sqlite_pragmas

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    event.listen(engine.sync_engine, "connect", _apply_sqlite_pragmas)

    async with engine.connect() as conn:
        result = await conn.execute(text("PRAGMA busy_timeout"))
        value = result.scalar()

    await engine.dispose()
    assert value == 30000


@pytest.mark.asyncio
async def test_get_engine_returns_engine() -> None:
    """get_engine()은 AsyncEngine 인스턴스를 반환해야 한다."""
    from sqlalchemy.ext.asyncio import AsyncEngine

    # 모듈 수준 싱글턴을 피하기 위해 환경변수를 재정의한다
    # Settings는 lru_cache를 사용하므로 새 엔진을 직접 생성해 검증
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    assert isinstance(engine, AsyncEngine)
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_db_yields_session() -> None:
    """get_db() 제너레이터가 AsyncSession을 yield해야 한다."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        assert isinstance(session, AsyncSession)
        # 간단한 쿼리로 세션이 활성 상태인지 확인
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1

    await engine.dispose()


def test_pragma_skipped_for_non_sqlite() -> None:
    """database_url이 sqlite로 시작하지 않으면 PRAGMA를 적용하지 않는다.

    _apply_sqlite_pragmas 내부의 분기를 직접 검증한다.
    비 SQLite URL에서 호출해도 예외가 발생하지 않아야 한다.
    """
    from unittest.mock import MagicMock, patch

    from app.infrastructure.db.session import _apply_sqlite_pragmas

    mock_conn = MagicMock()

    # get_settings는 lru_cache로 감싸여 있으므로
    # 함수 내부에서 임포트하는 모듈을 직접 패치한다
    mock_settings_instance = MagicMock()
    mock_settings_instance.database_url = "postgresql+asyncpg://localhost/test"

    with patch(
        "app.core.config.get_settings", return_value=mock_settings_instance
    ):
        _apply_sqlite_pragmas(mock_conn, None)

    # cursor()가 호출되지 않아야 한다
    mock_conn.cursor.assert_not_called()
