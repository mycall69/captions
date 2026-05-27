"""T015: ULID ID 생성기 단위 테스트."""

from app.core.ids import new_job_id, new_request_id, new_ulid

# Crockford Base32 알파벳 (I, L, O, U 제외)
_VALID_CHARS = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


class TestNewUlid:
    """new_ulid() 테스트."""

    def test_length_is_26(self) -> None:
        """ULID는 26자여야 한다."""
        result = new_ulid()
        assert len(result) == 26

    def test_alphabet_crockford_base32(self) -> None:
        """ULID는 Crockford Base32 알파벳만 포함해야 한다."""
        result = new_ulid()
        assert all(c in _VALID_CHARS for c in result), f"유효하지 않은 문자 포함: {result}"

    def test_monotonic_within_millisecond(self) -> None:
        """같은 ms 안에서도 사전순 단조 증가해야 한다 (ULID 스펙 §3.1)."""
        from itertools import pairwise

        ids = [new_ulid() for _ in range(1000)]
        for prev, curr in pairwise(ids):
            assert prev < curr, f"단조성 위배: {prev} >= {curr}"

    def test_uniqueness(self) -> None:
        """연속 생성된 ULID는 서로 달라야 한다."""
        ids = {new_ulid() for _ in range(100)}
        assert len(ids) == 100, "ULID 중복 발생"


class TestNewJobId:
    """new_job_id() 테스트."""

    def test_returns_ulid(self) -> None:
        """job_id는 26자 ULID 형식이어야 한다."""
        result = new_job_id()
        assert len(result) == 26
        assert all(c in _VALID_CHARS for c in result)


class TestNewRequestId:
    """new_request_id() 테스트."""

    def test_returns_ulid(self) -> None:
        """request_id는 26자 ULID 형식이어야 한다."""
        result = new_request_id()
        assert len(result) == 26
        assert all(c in _VALID_CHARS for c in result)
