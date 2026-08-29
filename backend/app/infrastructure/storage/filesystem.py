"""T020: 파일시스템 스토리지 추상화.

var/storage/<job_id>/ 하위에 job별 디렉터리를 생성·관리한다.
모든 경로는 sanitize_path()를 통해 path traversal 공격을 방지한다.

디렉터리 구조:
    var/storage/
    └── <job_id>/
        ├── <youtube_id>.mp4   # 다운로드된 원본 영상 (자막 파일과 prefix 동일)
        ├── <youtube_id>.ja.srt # 원본 자막 (예시, yt-dlp --convert-subs srt 결과)
        ├── <youtube_id>.ko.srt # target 자막 (영상에 임베디드된 경우)
        ├── dual.srt           # dual subtitle SRT
        ├── dual.vtt           # dual subtitle VTT
        └── tmp/               # 처리 중 임시 파일 (완료 후 삭제)
"""

from __future__ import annotations

import shutil
from pathlib import Path

from app.core.config import get_settings
from app.core.security import sanitize_path


class JobStorage:
    """job별 파일시스템 경로를 관리하는 스토리지 추상화 클래스.

    모든 경로 생성은 sanitize_path()를 거쳐 root 외부 이탈을 방지한다.
    root 디렉터리는 초기화 시 자동 생성된다.

    Args:
        root: 스토리지 루트 디렉터리. None이면 Settings.storage_root를 사용한다.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path(get_settings().storage_root)).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        """job 전용 디렉터리 경로를 반환한다. 존재하지 않으면 생성한다.

        Args:
            job_id: 작업 식별자 (ULID 등).

        Returns:
            job 디렉터리 절대 경로.

        Raises:
            InvalidPathError: job_id에 path traversal 문자열이 포함된 경우.
        """
        path = sanitize_path(self.root, job_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def tmp_dir(self, job_id: str) -> Path:
        """job 임시 디렉터리 경로를 반환한다. 존재하지 않으면 생성한다.

        워커 task 완료 후 즉시 삭제해야 한다.

        Args:
            job_id: 작업 식별자.

        Returns:
            tmp/ 서브디렉터리 절대 경로.

        Raises:
            InvalidPathError: path traversal 시도.
        """
        path = sanitize_path(self.job_dir(job_id), "tmp")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def video_path(self, job_id: str, youtube_video_id: str | None = None) -> Path:
        """다운로드된 원본 영상 파일 경로를 반환한다.

        파일명은 ``<youtube_video_id>.mp4`` 규약을 따른다 (자막 파일과 동일 prefix).
        ``youtube_video_id`` 가 주어지지 않으면 ``video.mp4`` 로 fallback —
        멱등성 호환을 위해 유지 (호출자가 video_id 를 모르는 케이스 / 레거시).

        Args:
            job_id: 작업 식별자.
            youtube_video_id: 영상 ID. 주어지면 ``<id>.mp4`` 로 저장 위치 결정.

        Returns:
            영상 파일 경로 (파일이 없을 수도 있음).
        """
        filename = (
            f"{youtube_video_id}.mp4" if youtube_video_id else "video.mp4"
        )
        return sanitize_path(self.job_dir(job_id), filename)

    def subtitle_path(self, job_id: str, name: str) -> Path:
        """자막 파일 경로를 반환한다.

        Args:
            job_id: 작업 식별자.
            name: 파일명. 예: "source.ja.vtt", "translated.ko.vtt",
                         "dual.srt", "dual.vtt".

        Returns:
            자막 파일 절대 경로.

        Raises:
            InvalidPathError: name에 path traversal 문자열이 포함된 경우.
        """
        return sanitize_path(self.job_dir(job_id), name)

    def purge_job_directory(self, job_id: str) -> None:
        """job 디렉터리 전체를 삭제한다.

        작업 취소(USER_CANCELLED) 또는 실패 후 정리 시 호출된다.
        T103 (US2 cancel) 구현에서도 재사용된다.

        디렉터리가 존재하지 않는 경우에도 오류 없이 종료한다.

        Args:
            job_id: 삭제할 작업 식별자.
        """
        # sanitize_path로 경로를 검증한 뒤 삭제
        # job_dir()은 디렉터리를 생성하므로, 경로 계산만 수행하기 위해
        # sanitize_path를 직접 호출한다.
        path = sanitize_path(self.root, job_id)
        shutil.rmtree(path, ignore_errors=True)
