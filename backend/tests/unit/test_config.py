"""T011: Settings 설정 로더 단위 테스트."""

from app.core.config import Settings, get_settings


class TestSettings:
    """Settings 클래스 테스트."""

    def test_default_values(self) -> None:
        """기본값이 quickstart §2와 일치해야 한다."""
        s = Settings()
        assert s.app_env == "local"
        assert s.log_level == "INFO"
        assert s.request_id_header == "x-request-id"
        assert s.job_concurrency == 2

    def test_allowed_hosts_list_splits_correctly(self) -> None:
        """allowed_hosts 콤마 분리가 올바르게 동작해야 한다."""
        s = Settings(
            allowed_hosts="youtube.com,www.youtube.com,m.youtube.com,youtu.be"
        )
        expected = ["youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"]
        assert s.allowed_hosts_list == expected

    def test_allowed_hosts_list_strips_whitespace(self) -> None:
        """공백이 포함된 허용 호스트도 올바르게 분리되어야 한다."""
        s = Settings(allowed_hosts="youtube.com , www.youtube.com")
        assert s.allowed_hosts_list == ["youtube.com", "www.youtube.com"]

    def test_job_concurrency_default(self) -> None:
        """기본 JOB_CONCURRENCY는 2여야 한다."""
        s = Settings()
        assert s.job_concurrency == 2

    def test_job_concurrency_clamps_zero(self) -> None:
        """JOB_CONCURRENCY=0이면 1로 클램프되어야 한다."""
        s = Settings(job_concurrency=0)  # type: ignore[arg-type]
        assert s.job_concurrency == 1

    def test_job_concurrency_clamps_negative(self) -> None:
        """JOB_CONCURRENCY=-5이면 1로 클램프되어야 한다."""
        s = Settings(job_concurrency=-5)  # type: ignore[arg-type]
        assert s.job_concurrency == 1

    def test_job_concurrency_valid_value(self) -> None:
        """유효한 JOB_CONCURRENCY 값은 그대로 유지되어야 한다."""
        s = Settings(job_concurrency=4)
        assert s.job_concurrency == 4

    def test_job_concurrency_string_zero(self) -> None:
        """문자열 '0'도 1로 클램프되어야 한다 (환경변수는 문자열로 들어옴)."""
        s = Settings(job_concurrency="0")  # type: ignore[arg-type]
        assert s.job_concurrency == 1

    def test_job_concurrency_invalid_string_defaults(self) -> None:
        """파싱 불가 문자열이면 기본값 2로 설정되어야 한다."""
        s = Settings(job_concurrency="abc")  # type: ignore[arg-type]
        assert s.job_concurrency == 2


class TestGetSettings:
    """get_settings() 캐시 함수 테스트."""

    def test_returns_settings_instance(self) -> None:
        """get_settings()는 Settings 인스턴스를 반환해야 한다."""
        s = get_settings()
        assert isinstance(s, Settings)
