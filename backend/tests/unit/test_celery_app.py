"""T026: Celery 앱 구성 단위 테스트."""

from app.workers.celery_app import celery_app


class TestCeleryAppConfig:
    """celery_app.conf 핵심 설정 검증."""

    def test_serializer_json_only(self) -> None:
        """JSON serializer 단일 사용 — 보안/호환성."""
        assert celery_app.conf.task_serializer == "json"
        assert celery_app.conf.result_serializer == "json"
        assert celery_app.conf.accept_content == ["json"]

    def test_utc_timezone(self) -> None:
        """모든 timestamp는 UTC 기준."""
        assert celery_app.conf.timezone == "UTC"
        assert celery_app.conf.enable_utc is True

    def test_long_task_safe_defaults(self) -> None:
        """긴 작업(다운로드·번역)에 적합한 acks_late + prefetch_multiplier=1."""
        assert celery_app.conf.task_acks_late is True
        assert celery_app.conf.worker_prefetch_multiplier == 1

    def test_retry_defaults(self) -> None:
        """retry 기본값이 설정되어 있다."""
        assert celery_app.conf.task_default_retry_delay == 2
        assert celery_app.conf.task_default_max_retries == 3

    def test_broker_from_settings(self) -> None:
        """broker / backend는 Settings에서 주입된다."""
        from app.core.config import get_settings

        settings = get_settings()
        assert celery_app.conf.broker_url == settings.celery_broker_url
        assert celery_app.conf.result_backend == settings.celery_result_backend
