"""T020: 파일시스템 스토리지 추상화 단위 테스트.

JobStorage 클래스의 경로 생성, 보안 검증, 디렉터리 삭제 동작을 검증한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.exceptions import InvalidPathError
from app.infrastructure.storage.filesystem import JobStorage


class TestJobStorageInit:
    """JobStorage 초기화 테스트."""

    def test_creates_root_directory(self, tmp_path: Path) -> None:
        """초기화 시 root 디렉터리가 존재하지 않으면 생성해야 한다."""
        root = tmp_path / "storage"
        assert not root.exists()
        JobStorage(root=root)
        assert root.is_dir()

    def test_root_is_resolved_to_absolute(self, tmp_path: Path) -> None:
        """root 속성은 항상 절대 경로여야 한다."""
        storage = JobStorage(root=tmp_path)
        assert storage.root.is_absolute()

    def test_accepts_existing_directory(self, tmp_path: Path) -> None:
        """이미 존재하는 디렉터리로 초기화해도 오류가 없어야 한다."""
        storage = JobStorage(root=tmp_path)
        assert storage.root == tmp_path.resolve()


class TestJobDir:
    """job_dir() 메서드 테스트."""

    def test_creates_job_directory(self, tmp_path: Path) -> None:
        """job_dir()은 job_id 이름의 서브디렉터리를 생성해야 한다."""
        storage = JobStorage(root=tmp_path)
        job_dir = storage.job_dir("01JTEST00000000001")
        assert job_dir.is_dir()

    def test_job_dir_inside_root(self, tmp_path: Path) -> None:
        """job_dir() 결과는 root 하위여야 한다."""
        storage = JobStorage(root=tmp_path)
        job_dir = storage.job_dir("01JTEST00000000001")
        assert str(job_dir).startswith(str(tmp_path.resolve()))

    def test_job_dir_same_call_idempotent(self, tmp_path: Path) -> None:
        """동일 job_id로 반복 호출해도 오류가 없어야 한다."""
        storage = JobStorage(root=tmp_path)
        dir1 = storage.job_dir("01JTEST00000000001")
        dir2 = storage.job_dir("01JTEST00000000001")
        assert dir1 == dir2

    def test_rejects_dotdot_job_id(self, tmp_path: Path) -> None:
        """.. 포함 job_id는 InvalidPathError를 발생시켜야 한다."""
        storage = JobStorage(root=tmp_path)
        with pytest.raises(InvalidPathError):
            storage.job_dir("../bad")

    def test_rejects_absolute_job_id(self, tmp_path: Path) -> None:
        """/로 시작하는 job_id는 InvalidPathError를 발생시켜야 한다."""
        storage = JobStorage(root=tmp_path)
        with pytest.raises(InvalidPathError):
            storage.job_dir("/etc/passwd")

    def test_rejects_null_byte_job_id(self, tmp_path: Path) -> None:
        """null 바이트 포함 job_id는 InvalidPathError를 발생시켜야 한다."""
        storage = JobStorage(root=tmp_path)
        with pytest.raises(InvalidPathError):
            storage.job_dir("job\x00id")


class TestTmpDir:
    """tmp_dir() 메서드 테스트."""

    def test_creates_tmp_subdirectory(self, tmp_path: Path) -> None:
        """tmp_dir()은 job_dir/tmp 서브디렉터리를 생성해야 한다."""
        storage = JobStorage(root=tmp_path)
        tmp = storage.tmp_dir("01JTEST00000000001")
        assert tmp.is_dir()
        assert tmp.name == "tmp"

    def test_tmp_dir_inside_job_dir(self, tmp_path: Path) -> None:
        """tmp_dir()은 job_dir 하위에 있어야 한다."""
        storage = JobStorage(root=tmp_path)
        job_dir = storage.job_dir("01JTEST00000000001")
        tmp = storage.tmp_dir("01JTEST00000000001")
        assert str(tmp).startswith(str(job_dir))


class TestVideoPaths:
    """video_path() 메서드 테스트."""

    def test_video_path_name_fallback(self, tmp_path: Path) -> None:
        """youtube_video_id 미지정 시 video.mp4 fallback 을 유지해야 한다 (레거시 호환)."""
        storage = JobStorage(root=tmp_path)
        path = storage.video_path("01JTEST00000000001")
        assert path.name == "video.mp4"

    def test_video_path_uses_youtube_id(self, tmp_path: Path) -> None:
        """youtube_video_id 가 주어지면 <id>.mp4 파일명을 사용해야 한다."""
        storage = JobStorage(root=tmp_path)
        path = storage.video_path("01JTEST00000000001", youtube_video_id="4EeTnIV05j4")
        assert path.name == "4EeTnIV05j4.mp4"

    def test_video_path_inside_job_dir(self, tmp_path: Path) -> None:
        """video_path()는 job_dir 하위 경로여야 한다."""
        storage = JobStorage(root=tmp_path)
        job_dir = storage.job_dir("01JTEST00000000001")
        path = storage.video_path("01JTEST00000000001", youtube_video_id="abcdefghijk")
        assert str(path).startswith(str(job_dir))


class TestSubtitlePath:
    """subtitle_path() 메서드 테스트."""

    @pytest.mark.parametrize("name", [
        "source.ja.vtt",
        "translated.ko.vtt",
        "dual.srt",
        "dual.vtt",
    ])
    def test_subtitle_path_returns_correct_name(self, tmp_path: Path, name: str) -> None:
        """subtitle_path()는 지정한 파일명의 경로를 반환해야 한다."""
        storage = JobStorage(root=tmp_path)
        path = storage.subtitle_path("01JTEST00000000001", name)
        assert path.name == name

    def test_subtitle_path_rejects_traversal(self, tmp_path: Path) -> None:
        """.. 포함 파일명은 InvalidPathError를 발생시켜야 한다."""
        storage = JobStorage(root=tmp_path)
        with pytest.raises(InvalidPathError):
            storage.subtitle_path("01JTEST00000000001", "../secret.txt")


class TestPurgeJobDirectory:
    """purge_job_directory() 메서드 테스트."""

    def test_removes_existing_directory(self, tmp_path: Path) -> None:
        """purge_job_directory()는 job 디렉터리 전체를 삭제해야 한다."""
        storage = JobStorage(root=tmp_path)
        job_dir = storage.job_dir("01JTEST00000000001")

        # 파일 생성
        (job_dir / "video.mp4").write_bytes(b"fake")
        assert job_dir.exists()

        storage.purge_job_directory("01JTEST00000000001")
        assert not job_dir.exists()

    def test_idempotent_on_missing_directory(self, tmp_path: Path) -> None:
        """존재하지 않는 디렉터리 삭제 시도는 오류 없이 완료해야 한다."""
        storage = JobStorage(root=tmp_path)
        # job_dir을 생성하지 않고 바로 purge
        storage.purge_job_directory("nonexistent-job")  # 예외 없어야 함

    def test_rejects_traversal_in_purge(self, tmp_path: Path) -> None:
        """purge 시 .. 포함 job_id는 InvalidPathError를 발생시켜야 한다."""
        storage = JobStorage(root=tmp_path)
        with pytest.raises(InvalidPathError):
            storage.purge_job_directory("../escape")
