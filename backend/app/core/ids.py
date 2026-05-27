"""T015: ULID 기반 ID 생성기.

서드파티 ULID 라이브러리 없이 순수 구현.
- new_ulid(): 26자 Crockford Base32 ULID
- new_job_id(): 작업 ID 생성
- new_request_id(): 요청 ID 생성
"""

import secrets
import time

# Crockford Base32 알파벳 (혼동 문자 제거: I, L, O, U)
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode_base32(value: int, length: int) -> str:
    """정수를 Crockford Base32로 인코딩 (고정 길이)."""
    out = []
    for _ in range(length):
        out.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(out))


def new_ulid() -> str:
    """26자 ULID 생성.

    형식: 10자 타임스탬프(ms) + 16자 난수 (Crockford Base32).
    """
    ts_ms = int(time.time() * 1000)
    rand = secrets.randbits(80)
    return _encode_base32(ts_ms, 10) + _encode_base32(rand, 16)


def new_job_id() -> str:
    """작업 ID 생성 (ULID 기반)."""
    return new_ulid()


def new_request_id() -> str:
    """요청 ID 생성 (ULID 기반)."""
    return new_ulid()
