"""T016: 비동기 SQLAlchemy 엔진 및 세션 팩토리.

SQLite WAL 모드를 활성화하고, 외래 키 제약 및 동시성 설정을 적용한다.
모듈 임포트 시점에는 연결을 생성하지 않는다 (지연 초기화).

설정:
- journal_mode=WAL  : 읽기·쓰기 동시성 향상
- synchronous=NORMAL: WAL 모드에서 권장하는 내구성/성능 균형
- foreign_keys=ON   : 외래 키 제약 시행
- busy_timeout=30000: 잠금 대기 최대 30초 (워커 쓰기 직렬화)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    pass

# ── 지연 초기화 싱글턴 ────────────────────────────────────────────────────────

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _apply_sqlite_pragmas(dbapi_conn: object, _connection_record: object) -> None:
    """SQLite 연결에 WAL 및 보안 PRAGMA를 적용한다.

    SQLite 이외의 DB(PostgreSQL 등)에서는 아무 동작도 하지 않는다.
    이 함수는 SQLAlchemy 'connect' 이벤트에 등록된다.
    """
    import sqlite3

    from app.core.config import get_settings

    if not get_settings().database_url.startswith("sqlite"):
        return

    # dbapi_conn은 sqlite3.Connection 또는 aiosqlite 래퍼 인스턴스임
    # hasattr로 duck-typing 검사한다
    if not hasattr(dbapi_conn, "cursor"):
        return
    conn: sqlite3.Connection = dbapi_conn  # type: ignore[assignment]
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


def get_engine() -> AsyncEngine:
    """비동기 SQLAlchemy 엔진을 반환한다 (최초 호출 시 생성).

    모듈 임포트 시점에는 연결을 열지 않아, 테스트에서
    database_url을 재정의한 뒤 임포트해도 안전하다.
    """
    global _engine
    if _engine is None:
        from app.core.config import get_settings

        _engine = create_async_engine(
            get_settings().database_url,
            echo=False,
            pool_pre_ping=True,
        )
        # SQLite WAL pragma 리스너 등록
        # sync_engine을 통해 DBAPI 연결 이벤트를 캡처한다
        event.listen(_engine.sync_engine, "connect", _apply_sqlite_pragmas)

    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """비동기 세션 팩토리를 반환한다 (최초 호출 시 생성)."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
        )
    return _sessionmaker


# FastAPI 의존성 주입용 편의 alias
AsyncSessionLocal = get_sessionmaker


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """요청 범위 DB 세션을 생성하는 FastAPI 의존성.

    세션은 트랜잭션 컨텍스트 안에서 yield되며, 요청 완료 후 자동 종료된다.
    예외 발생 시 rollback은 SQLAlchemy 세션 컨텍스트 매니저가 처리한다.

    Usage:
        @router.get("/example")
        async def example(db: AsyncSession = Depends(get_db)):
            ...
    """
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        yield session
