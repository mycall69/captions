"""Alembic 마이그레이션 환경 설정.

Settings.database_url을 읽어 Alembic 동기 엔진을 구성한다.
aiosqlite URL은 sqlite:// 로 변환해 Alembic 내부 동기 엔진에 전달한다.
"""

from __future__ import annotations

import re
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings

# ORM Base를 임포트해 autogenerate가 모든 테이블을 인식하게 한다
from app.infrastructure.db import orm

# Alembic Config 객체 (alembic.ini 값 접근용)
config = context.config

# fileConfig로 로깅 설정
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# autogenerate 대상 메타데이터
target_metadata = orm.Base.metadata


def _sync_url(url: str) -> str:
    """비동기 드라이버 URL을 Alembic 동기 엔진용 URL로 변환한다.

    - sqlite+aiosqlite:// → sqlite://
    - postgresql+asyncpg:// → postgresql://
    """
    url = re.sub(r"\+aiosqlite", "", url)
    url = re.sub(r"\+asyncpg", "", url)
    return url


def _get_url() -> str:
    """Settings에서 동기화된 DB URL을 반환한다."""
    return _sync_url(get_settings().database_url)


def run_migrations_offline() -> None:
    """오프라인 모드 마이그레이션 실행.

    DB 연결 없이 SQL 스크립트만 생성한다.
    """
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite ALTER TABLE 지원
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """온라인 모드 마이그레이션 실행.

    실제 DB 연결을 통해 마이그레이션을 적용한다.
    """
    # alembic.ini의 sqlalchemy.url을 Settings 값으로 오버라이드
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite ALTER TABLE 지원
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
