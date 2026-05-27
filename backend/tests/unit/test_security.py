"""T012: URL 검증 및 경로 보안 단위 테스트."""

from pathlib import Path

import pytest

from app.core.exceptions import InvalidPathError, InvalidUrlError
from app.core.security import parse_youtube_url, sanitize_path


class TestParseYoutubeUrl:
    """parse_youtube_url() 테스트."""

    # ── 유효한 URL 형태 ─────────────────────────────────────────────────────

    def test_watch_url(self) -> None:
        """표준 youtube.com/watch?v= URL에서 ID를 추출한다."""
        assert parse_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcY") == "dQw4w9WgXcY"

    def test_watch_url_no_www(self) -> None:
        """www 없는 youtube.com/watch?v= URL도 처리한다."""
        assert parse_youtube_url("https://youtube.com/watch?v=dQw4w9WgXcY") == "dQw4w9WgXcY"

    def test_mobile_url(self) -> None:
        """m.youtube.com 모바일 URL도 처리한다."""
        assert parse_youtube_url("https://m.youtube.com/watch?v=dQw4w9WgXcY") == "dQw4w9WgXcY"

    def test_short_url(self) -> None:
        """youtu.be/<id> 단축 URL에서 ID를 추출한다."""
        assert parse_youtube_url("https://youtu.be/dQw4w9WgXcY") == "dQw4w9WgXcY"

    def test_shorts_url(self) -> None:
        """youtube.com/shorts/<id> URL에서 ID를 추출한다."""
        assert parse_youtube_url("https://www.youtube.com/shorts/dQw4w9WgXcY") == "dQw4w9WgXcY"

    def test_embed_url(self) -> None:
        """youtube.com/embed/<id> URL에서 ID를 추출한다."""
        assert parse_youtube_url("https://www.youtube.com/embed/dQw4w9WgXcY") == "dQw4w9WgXcY"

    def test_url_with_timestamp(self) -> None:
        """t= 파라미터가 있어도 ID를 올바르게 추출한다."""
        assert (
            parse_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcY&t=42")
            == "dQw4w9WgXcY"
        )

    def test_url_with_list_and_v(self) -> None:
        """list= 파라미터가 있어도 v= 파라미터로 ID를 추출한다."""
        assert (
            parse_youtube_url(
                "https://www.youtube.com/watch?v=dQw4w9WgXcY&list=PLabcdefg"
            )
            == "dQw4w9WgXcY"
        )

    def test_id_with_special_chars(self) -> None:
        """_와 - 포함된 유효한 11자 ID를 처리한다."""
        assert parse_youtube_url("https://www.youtube.com/watch?v=abc-DEF_xyz") == "abc-DEF_xyz"

    # ── 허용되지 않는 호스트 ────────────────────────────────────────────────

    def test_rejects_non_youtube_host(self) -> None:
        """YouTube가 아닌 호스트는 InvalidUrlError를 발생시킨다."""
        with pytest.raises(InvalidUrlError, match="유효한 YouTube"):
            parse_youtube_url("https://vimeo.com/watch?v=dQw4w9WgXcY")

    def test_rejects_evil_host(self) -> None:
        """악의적 호스트는 거절된다."""
        with pytest.raises(InvalidUrlError):
            parse_youtube_url("https://evil.youtube.com/watch?v=dQw4w9WgXcY")

    def test_rejects_non_http_scheme(self) -> None:
        """http/https 이외의 스킴은 거절된다."""
        with pytest.raises(InvalidUrlError):
            parse_youtube_url("ftp://www.youtube.com/watch?v=dQw4w9WgXcY")

    # ── playlist URL 거절 ───────────────────────────────────────────────────

    def test_rejects_playlist_path(self) -> None:
        """/playlist 경로 URL은 InvalidUrlError를 발생시킨다."""
        with pytest.raises(InvalidUrlError, match="재생목록"):
            parse_youtube_url("https://www.youtube.com/playlist?list=PLxxxxx")

    def test_rejects_list_only_no_v(self) -> None:
        """list= 파라미터만 있고 v=가 없는 URL은 거절된다."""
        with pytest.raises(InvalidUrlError, match="재생목록"):
            parse_youtube_url("https://www.youtube.com/watch?list=PLxxxxx")

    # ── 잘못된 영상 ID 길이 ─────────────────────────────────────────────────

    def test_rejects_10_char_id(self) -> None:
        """10자 ID는 InvalidUrlError를 발생시킨다."""
        with pytest.raises(InvalidUrlError):
            parse_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXc")  # 10자

    def test_rejects_12_char_id(self) -> None:
        """12자 ID는 InvalidUrlError를 발생시킨다."""
        with pytest.raises(InvalidUrlError):
            parse_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcYZ")  # 12자

    def test_rejects_empty_v_param(self) -> None:
        """v= 값이 없는 URL은 거절된다."""
        with pytest.raises(InvalidUrlError):
            parse_youtube_url("https://www.youtube.com/watch?v=")

    def test_rejects_no_id(self) -> None:
        """ID를 포함하지 않는 URL은 거절된다."""
        with pytest.raises(InvalidUrlError):
            parse_youtube_url("https://www.youtube.com/")


class TestSanitizePath:
    """sanitize_path() 테스트."""

    def test_valid_path(self, tmp_path: Path) -> None:
        """유효한 경로는 base 하위의 절대 경로를 반환한다."""
        result = sanitize_path(tmp_path, "jobs", "some_job_id")
        assert result.is_absolute()
        assert str(result).startswith(str(tmp_path.resolve()))

    def test_rejects_dotdot(self, tmp_path: Path) -> None:
        """.. 포함 경로는 InvalidPathError를 발생시킨다."""
        with pytest.raises(InvalidPathError, match="상위 디렉터리"):
            sanitize_path(tmp_path, "..", "etc", "passwd")

    def test_rejects_absolute_part(self, tmp_path: Path) -> None:
        """/로 시작하는 절대 경로 구성요소는 거절된다."""
        with pytest.raises(InvalidPathError, match="절대 경로"):
            sanitize_path(tmp_path, "/etc/passwd")

    def test_rejects_null_byte(self, tmp_path: Path) -> None:
        """null 바이트 포함 경로는 거절된다."""
        with pytest.raises(InvalidPathError, match="허용되지 않는 문자"):
            sanitize_path(tmp_path, "jobs\x00evil")

    def test_rejects_traversal_in_middle(self, tmp_path: Path) -> None:
        """중간에 .. 포함된 경로도 거절된다."""
        with pytest.raises(InvalidPathError):
            sanitize_path(tmp_path, "jobs", "..", "..", "etc")

    def test_nested_valid_path(self, tmp_path: Path) -> None:
        """여러 depth의 유효한 경로도 처리한다."""
        result = sanitize_path(tmp_path, "a", "b", "c")
        assert result == (tmp_path / "a" / "b" / "c").resolve()
