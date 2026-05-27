"""T049: URL 검증기 단위 테스트 (US1, FR-001, FR-002, research §9).

기존 test_security.py가 이미 다음을 커버함:
- test_watch_url, test_watch_url_no_www, test_mobile_url (m.youtube.com)
- test_short_url (youtu.be), test_shorts_url (/shorts/), test_embed_url (/embed/)
- test_url_with_timestamp, test_url_with_list_and_v
- test_id_with_special_chars
- test_rejects_non_youtube_host, test_rejects_evil_host, test_rejects_non_http_scheme
- test_rejects_playlist_path, test_rejects_list_only_no_v
- test_rejects_10_char_id, test_rejects_12_char_id, test_rejects_empty_v_param, test_rejects_no_id

본 파일은 test_security.py가 커버하지 않는 추가 케이스만 포함한다.
"""

from __future__ import annotations

import pytest

from app.core.exceptions import InvalidUrlError
from app.core.security import parse_youtube_url


class TestAdditionalYoutubeUrlCases:
    """test_security.py에서 다루지 않는 추가 URL 패턴 케이스."""

    # ── query string 변형 ─────────────────────────────────────────────────────

    def test_watch_url_with_si_tracking_param(self) -> None:
        """si= 추적 파라미터가 포함된 URL에서도 ID를 올바르게 추출한다."""
        assert (
            parse_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcY&si=xxxxxxxxxxx")
            == "dQw4w9WgXcY"
        )

    def test_watch_url_with_pp_param(self) -> None:
        """pp= 파라미터가 있어도 ID를 올바르게 추출한다."""
        assert (
            parse_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcY&pp=gAQB")
            == "dQw4w9WgXcY"
        )

    # ── 허용 호스트 경계 케이스 ────────────────────────────────────────────────

    @pytest.mark.parametrize(
        "allowed_host",
        [
            "https://www.youtube.com/watch?v=dQw4w9WgXcY",
            "https://youtube.com/watch?v=dQw4w9WgXcY",
            "https://m.youtube.com/watch?v=dQw4w9WgXcY",
            "https://youtu.be/dQw4w9WgXcY",
        ],
    )
    def test_all_allowed_hosts_accepted(self, allowed_host: str) -> None:
        """허용된 호스트 4종 모두에서 ID를 추출할 수 있어야 한다 (research §9)."""
        result = parse_youtube_url(allowed_host)
        assert result == "dQw4w9WgXcY"

    @pytest.mark.parametrize(
        "rejected_url",
        [
            "https://youtu.be.evil.com/dQw4w9WgXcY",
            "https://www.youtube.com.evil.com/watch?v=dQw4w9WgXcY",
            "http://youtube.co/watch?v=dQw4w9WgXcY",
            "https://fakeyoutube.com/watch?v=dQw4w9WgXcY",
        ],
    )
    def test_subdomain_spoofing_rejected(self, rejected_url: str) -> None:
        """subdomain/TLD spoofing URL은 모두 거절되어야 한다."""
        with pytest.raises(InvalidUrlError):
            parse_youtube_url(rejected_url)

    # ── 특수 URL 형태 ──────────────────────────────────────────────────────────

    def test_shorts_without_www(self) -> None:
        """www 없는 youtube.com/shorts/ URL도 처리해야 한다."""
        assert parse_youtube_url("https://youtube.com/shorts/dQw4w9WgXcY") == "dQw4w9WgXcY"

    def test_embed_without_www(self) -> None:
        """www 없는 youtube.com/embed/ URL도 처리해야 한다."""
        assert parse_youtube_url("https://youtube.com/embed/dQw4w9WgXcY") == "dQw4w9WgXcY"

    def test_url_with_fragment_ignored(self) -> None:
        """fragment(#)가 있어도 ID를 올바르게 추출한다."""
        assert (
            parse_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcY#t=42")
            == "dQw4w9WgXcY"
        )

    # ── 명시적 playlist 거절 ───────────────────────────────────────────────────

    def test_playlist_with_video_id_still_rejects_if_playlist_path(self) -> None:
        """/playlist 경로는 v= 파라미터가 있어도 거절되어야 한다."""
        with pytest.raises(InvalidUrlError):
            parse_youtube_url(
                "https://www.youtube.com/playlist?list=PLxxxxx&v=dQw4w9WgXcY"
            )

    # ── edge 케이스 ────────────────────────────────────────────────────────────

    def test_empty_string_rejected(self) -> None:
        """빈 문자열은 InvalidUrlError를 발생시켜야 한다."""
        with pytest.raises(InvalidUrlError):
            parse_youtube_url("")

    def test_whitespace_only_rejected(self) -> None:
        """공백만 있는 문자열은 거절되어야 한다."""
        with pytest.raises(InvalidUrlError):
            parse_youtube_url("   ")
