"""T011: 환경 변수 기반 설정 로더.

pydantic-settings를 이용해 .env 파일 및 환경 변수에서 값을 로드한다.
quickstart.md §2의 키 목록 전체 포함. JOB_CONCURRENCY는 최소 1로 클램프.
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── 공통 ────────────────────────────────────────────────────────────────
    app_env: str = "local"
    log_level: str = "INFO"
    request_id_header: str = "x-request-id"

    # ── 데이터 / 스토리지 ────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./var/db/app.db"
    storage_root: str = "./var/storage"

    # ── 큐 ──────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ── 번역 provider ────────────────────────────────────────────────────────
    translation_provider: str = "claude"
    anthropic_api_key: str = ""
    translation_model: str = "claude-opus-4-7"

    # ── 보안 / rate limit ────────────────────────────────────────────────────
    rate_limit_per_min: int = 10
    allowed_hosts: str = "youtube.com,www.youtube.com,m.youtube.com,youtu.be"

    # ── 동시성 (spec Clarifications Q5) ─────────────────────────────────────
    # 환경변수가 1 미만이면 1로 클램프
    job_concurrency: int = Field(default=2, ge=1)

    # ── 테스트 / 개발 전용 ─────────────────────────────────────────────────────
    # True이면 POST /v1/jobs에서 Celery chain 디스패치를 건너뛴다 (테스트 격리용)
    disable_chain_dispatch: bool = False

    @field_validator("job_concurrency", mode="before")
    @classmethod
    def _clamp(cls, v: object) -> int:
        """JOB_CONCURRENCY를 최소 1로 클램프."""
        try:
            n = int(str(v))
        except (TypeError, ValueError):
            return 2
        return max(1, n)

    @property
    def allowed_hosts_list(self) -> list[str]:
        """허용 호스트 목록을 콤마 분리 후 반환."""
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]


@lru_cache
def get_settings() -> Settings:
    """설정 싱글턴 반환 (lru_cache로 반복 파싱 방지)."""
    return Settings()
