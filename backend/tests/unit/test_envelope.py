"""T014: 응답 envelope 단위 테스트."""

from app.api.v1.envelope import Envelope, ErrorBody, error_envelope, success_envelope


class TestSuccessEnvelope:
    """success_envelope() 테스트."""

    def test_basic_shape(self) -> None:
        """성공 envelope의 기본 구조를 검증한다."""
        result = success_envelope({"id": "123"}, "req-abc")
        assert result["success"] is True
        assert result["data"] == {"id": "123"}
        assert result["request_id"] == "req-abc"

    def test_no_error_key(self) -> None:
        """성공 envelope에는 error 키가 포함되지 않아야 한다."""
        result = success_envelope(None, "req-abc")
        assert "error" not in result

    def test_none_data(self) -> None:
        """data가 None이어도 올바르게 처리된다."""
        result = success_envelope(None, "req-xyz")
        assert result["data"] is None
        assert result["success"] is True


class TestErrorEnvelope:
    """error_envelope() 테스트."""

    def test_basic_shape(self) -> None:
        """오류 envelope의 기본 구조를 검증한다."""
        result = error_envelope("INVALID_URL", "유효하지 않은 URL", "req-def")
        assert result["success"] is False
        assert isinstance(result["error"], dict)
        error = result["error"]
        assert error["code"] == "INVALID_URL"  # type: ignore[index]
        assert error["message"] == "유효하지 않은 URL"  # type: ignore[index]
        assert result["request_id"] == "req-def"

    def test_omits_details_when_none(self) -> None:
        """details가 None이면 error body에 포함되지 않아야 한다."""
        result = error_envelope("NOT_FOUND", "리소스 없음", "req-ghi", details=None)
        error = result["error"]
        assert "details" not in error  # type: ignore[operator]

    def test_includes_details_when_provided(self) -> None:
        """details가 제공되면 error body에 포함되어야 한다."""
        details = {"duration_sec": 8123, "max_duration_sec": 7200}
        result = error_envelope("INVALID_INPUT", "영상 길이 초과", "req-jkl", details=details)
        error = result["error"]
        assert error["details"] == details  # type: ignore[index]

    def test_no_data_key(self) -> None:
        """오류 envelope에는 data 키가 포함되지 않아야 한다."""
        result = error_envelope("INTERNAL_ERROR", "서버 오류", "req-mno")
        assert "data" not in result


class TestEnvelopeModel:
    """Envelope Pydantic 모델 테스트."""

    def test_success_model(self) -> None:
        """성공 Envelope 모델을 생성할 수 있어야 한다."""
        env = Envelope[dict](success=True, data={"key": "val"}, request_id="req-1")
        assert env.success is True
        assert env.error is None

    def test_error_model(self) -> None:
        """오류 Envelope 모델을 생성할 수 있어야 한다."""
        err = ErrorBody(code="NOT_FOUND", message="없음")
        env = Envelope[None](success=False, error=err, request_id="req-2")
        assert env.success is False
        assert env.data is None
