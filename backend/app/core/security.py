"""T012: URL 검증 및 경로 보안 유틸리티.

research.md §9 기반:
- parse_youtube_url(): 허용 호스트 검증 + 11자 영상 ID 추출
- sanitize_path(): path traversal 방지
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import ParseResult, parse_qs, urlparse

from app.core.exceptions import InvalidPathError, InvalidUrlError

# 11자 YouTube 영상 ID 검증 패턴 (A-Za-z0-9_-)
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _extract_video_id(parsed: ParseResult) -> str | None:
    """파싱된 URL에서 11자 영상 ID를 추출한다.

    지원 URL 형태:
    - youtube.com/watch?v=XXX
    - youtu.be/XXX
    - m.youtube.com/watch?v=XXX
    - youtube.com/shorts/XXX
    - youtube.com/embed/XXX
    """
    path = parsed.path.rstrip("/")
    qs = parse_qs(parsed.query)

    # /watch?v= 형태
    if "v" in qs:
        candidate = qs["v"][0]
        if _VIDEO_ID_RE.match(candidate):
            return candidate

    # youtu.be/<id> / shorts/<id> / embed/<id> 형태
    segments = [seg for seg in path.split("/") if seg]
    if segments:
        # youtu.be/<id> 또는 경로 마지막 세그먼트가 ID인 경우
        for prefix in ("shorts", "embed"):
            if len(segments) >= 2 and segments[-2] == prefix:
                candidate = segments[-1]
                if _VIDEO_ID_RE.match(candidate):
                    return candidate

        # youtu.be 단축 URL: 경로 첫 세그먼트가 ID
        if parsed.hostname == "youtu.be":
            candidate = segments[0]
            if _VIDEO_ID_RE.match(candidate):
                return candidate

    return None


def parse_youtube_url(url: str) -> str:
    """YouTube URL에서 11자 영상 ID를 추출한다.

    Args:
        url: 검증할 YouTube URL 문자열.

    Returns:
        11자 YouTube 영상 ID.

    Raises:
        InvalidUrlError: 허용하지 않는 호스트, playlist URL, ID 추출 불가.
    """
    parsed = urlparse(url)

    # 스킴 확인
    if parsed.scheme not in ("http", "https"):
        raise InvalidUrlError(
            "유효한 YouTube 영상 URL이 아닙니다.",
            details={"reason": "허용되지 않는 스킴", "scheme": parsed.scheme},
        )

    # 호스트 allowlist 검증
    from app.core.config import get_settings

    hostname = (parsed.hostname or "").lower()
    allowed = get_settings().allowed_hosts_list
    if hostname not in allowed:
        raise InvalidUrlError(
            "유효한 YouTube 영상 URL이 아닙니다.",
            details={"reason": "허용되지 않는 호스트", "host": hostname},
        )

    path = parsed.path.rstrip("/")
    qs = parse_qs(parsed.query)

    # 명시적 playlist URL 거절 (/playlist 경로)
    if path == "/playlist" or path.startswith("/playlist/"):
        raise InvalidUrlError(
            "재생목록 URL은 지원하지 않습니다. 개별 영상 URL을 입력해 주세요.",
            details={"reason": "playlist URL"},
        )

    # list= 파라미터만 있고 v= 파라미터가 없는 경우 거절
    if "list" in qs and "v" not in qs:
        # youtu.be 등 경로 기반 ID 추출 가능 여부 확인
        video_id = _extract_video_id(parsed)
        if video_id is None:
            raise InvalidUrlError(
                "재생목록 URL은 지원하지 않습니다. 개별 영상 URL을 입력해 주세요.",
                details={"reason": "playlist-only URL (v= 없음)"},
            )
        return video_id

    # 영상 ID 추출
    video_id = _extract_video_id(parsed)
    if video_id is None:
        # 사용자 입력 URL은 자격증명 / 트래킹 토큰을 포함할 수 있어 응답 본문에 노출하지 않는다.
        raise InvalidUrlError(
            "유효한 YouTube 영상 URL이 아닙니다. 영상 ID를 찾을 수 없습니다.",
            details={"reason": "영상 ID 추출 실패", "host": hostname},
        )

    return video_id


def sanitize_path(base: Path, *parts: str) -> Path:
    """안전한 경로를 생성한다 (path traversal 방지).

    Args:
        base: 기준 디렉터리 경로.
        *parts: 기준 경로에 이어 붙일 경로 구성요소들.

    Returns:
        base 하위에 있음이 검증된 절대 경로.

    Raises:
        InvalidPathError: 상대 경로 탈출, 절대 경로 주입, null 바이트 등.
    """
    for part in parts:
        # null 바이트 거부
        if "\x00" in part:
            raise InvalidPathError(
                "경로에 허용되지 않는 문자가 포함되어 있습니다.",
                details={"reason": "null 바이트"},
            )
        # 절대 경로 거부
        if Path(part).is_absolute():
            raise InvalidPathError(
                "경로에 절대 경로를 사용할 수 없습니다.",
                details={"reason": "절대 경로", "part": part},
            )
        # .. 포함 여부 검사
        if ".." in Path(part).parts:
            raise InvalidPathError(
                "경로에 상위 디렉터리 참조(..)를 사용할 수 없습니다.",
                details={"reason": "path traversal", "part": part},
            )

    candidate = base.joinpath(*parts)
    resolved = candidate.resolve()
    base_resolved = base.resolve()

    # 결과 경로가 base 하위에 있는지 확인
    if not resolved.is_relative_to(base_resolved):
        raise InvalidPathError(
            "경로가 허용된 디렉터리를 벗어납니다.",
            details={"reason": "base 이탈", "resolved": str(resolved)},
        )

    return resolved
