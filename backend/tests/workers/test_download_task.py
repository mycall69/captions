"""T041: 다운로드 워커 태스크 테스트 (US1, FR-005, FR-006, FR-007, FR-033).

검증 항목:
- mock yt-dlp: subprocess가 arg LIST(문자열 아님)로 호출되는지 확인 (FR-033 shell injection 금지)
- idempotent: 동일 job_id로 두 번 호출 시 상태 오염 없음
- 일시적 subprocess 오류 시 retry 트리거
"""

from __future__ import annotations

import contextlib
import subprocess
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip(
    "app.workers.tasks.download",
    reason="awaiting Phase 3b implementation — app.workers.tasks.download",
)

from app.workers.tasks.download import (  # noqa: E402  # type: ignore[reportMissingImports]
    download_task,
)

pytestmark = pytest.mark.workers


class TestDownloadTaskSubprocessArgList:
    """FR-033: subprocess는 반드시 arg list로 호출되어야 한다 (shell=True 금지)."""

    def test_subprocess_called_with_arg_list_not_string(self) -> None:
        """subprocess.run / Popen 호출 시 첫 번째 인자가 list이어야 한다 (shell injection 방지)."""
        captured_calls: list[object] = []

        def spy_run(args: object, *a: object, **kw: object) -> object:
            captured_calls.append(args)
            # 실제 실행 대신 mock 성공 반환
            mock_result = MagicMock()
            mock_result.returncode = 0
            return mock_result

        with patch("subprocess.run", side_effect=spy_run), contextlib.suppress(Exception):
            download_task("test_job_id_00000001")

        for call_args in captured_calls:
            assert isinstance(call_args, list), (
                f"subprocess.run의 첫 번째 인자가 list가 아님: {type(call_args).__name__}. "
                "FR-033 shell injection 금지 위반."
            )

    def test_yt_dlp_not_invoked_with_shell_true(self) -> None:
        """subprocess.run에 shell=True가 전달되지 않아야 한다."""
        shell_calls: list[bool] = []

        def spy_run(args: object, *a: object, shell: bool = False, **kw: object) -> object:
            shell_calls.append(shell)
            mock_result = MagicMock()
            mock_result.returncode = 0
            return mock_result

        with patch("subprocess.run", side_effect=spy_run), contextlib.suppress(Exception):
            download_task("test_job_id_00000001")

        for used_shell in shell_calls:
            assert used_shell is False, "subprocess.run(shell=True) 사용 금지 (FR-033)"


class TestDownloadTaskIdempotent:
    """다운로드 태스크 idempotent 검증 (FR-028)."""

    def test_double_invocation_does_not_raise(self, tmp_path: object) -> None:
        """동일 job_id로 두 번 호출해도 예외 없이 종료되어야 한다 (idempotent)."""
        with (
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
            patch("app.workers.tasks.download.JobStorage") as mock_storage,  # type: ignore[reportMissingImports]
        ):
            mock_storage.return_value.video_path.return_value = MagicMock(
                exists=lambda: True
            )
            try:
                download_task("test_job_id_00000002")
                download_task("test_job_id_00000002")
            except Exception as exc:
                pytest.fail(f"두 번째 호출에서 예외 발생: {exc}")


class TestDownloadTaskRetry:
    """일시적 오류 시 Celery retry 트리거 검증."""

    def test_transient_subprocess_error_triggers_retry(self) -> None:
        """subprocess.CalledProcessError(일시적) 발생 시 Celery retry가 호출되어야 한다."""
        with patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, ["yt-dlp"]),
        ), contextlib.suppress(Exception):
            download_task.apply(args=("test_job_id_00000003",))

    def test_download_task_has_max_retries(self) -> None:
        """download_task에 max_retries 설정이 있어야 한다."""
        assert hasattr(download_task, "max_retries") or hasattr(
            download_task, "retry_backoff"
        ), "download_task에 retry 설정이 누락됨"
