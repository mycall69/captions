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
    # 헌법 VI — backend 로그(app.log) 적재 루트. 비활성화 불가.
    log_dir: str = "./logs"
    request_id_header: str = "x-request-id"

    # ── 데이터 / 스토리지 ────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./var/db/app.db"
    storage_root: str = "./var/storage"

    # ── 큐 ──────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ── 번역 provider ────────────────────────────────────────────────────────
    # 인증 우선순위: CLAUDE_CODE_OAUTH_TOKEN(Bearer) > ANTHROPIC_API_KEY(x-api-key).
    # OAuth 토큰은 Claude Code 구독에 묶이며 Anthropic 공식 지원 범위가 아니므로
    # 개인 개발/실험 용도로만 사용. 운영 환경은 ANTHROPIC_API_KEY 사용을 권장한다.
    translation_provider: str = "claude"
    anthropic_api_key: str = ""
    claude_code_oauth_token: str = ""
    translation_model: str = "claude-opus-4-7"

    # ── 보안 / rate limit ────────────────────────────────────────────────────
    rate_limit_per_min: int = 10
    allowed_hosts: str = "youtube.com,www.youtube.com,m.youtube.com,youtu.be"

    # ── yt-dlp 인증 (anti-bot 우회) ──────────────────────────────────────────
    # YouTube 가 "Sign in to confirm you're not a bot" 게이트를 띄워 자막/메타데이터
    # 다운로드를 차단하는 경우, 로컬 브라우저의 YouTube 쿠키를 사용해 인증된 세션으로
    # 호출한다. 값이 비어 있으면 옵션 미적용(기본 동작 유지).
    # 허용 값: safari | chrome | firefox | edge | brave | chromium | opera | vivaldi
    # 헌법 IV — 로컬 호스트 전제이므로 keychain/cookie store 접근은 운영 위험 낮음.
    yt_dlp_cookies_browser: str = ""

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
