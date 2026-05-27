"""T015: ULID 기반 ID 생성기.

서드파티 ULID 라이브러리 없이 순수 구현.
- new_ulid(): 26자 Crockford Base32 ULID, 같은 ms 안에서도 단조 증가 보장
- new_job_id(): 작업 ID 생성
- new_request_id(): 요청 ID 생성

DB 정렬·페이지네이션이 ULID에 의존하므로 단조성을 유지한다 (ULID 스펙 §3.1).
"""

import secrets
import threading
import time

# Crockford Base32 알파벳 (혼동 문자 제거: I, L, O, U)
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

# 단조성 상태 (프로세스 단위). 같은 ms 내 충돌 시 random part를 1씩 증가시킨다.
_RAND_MAX = (1 << 80) - 1
_state_lock = threading.Lock()
_last_ms = 0
_last_rand = 0


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
    같은 ms에 여러 번 호출되면 random part를 단조 증가시켜 정렬 가능성을 보장한다.
    """
    global _last_ms, _last_rand
    with _state_lock:
        ts_ms = int(time.time() * 1000)
        if ts_ms == _last_ms:
            # 같은 ms 충돌: 직전 random + 1. overflow하면 ms를 한 단위 진행.
            if _last_rand < _RAND_MAX:
                _last_rand += 1
            else:
                ts_ms = _last_ms + 1
                _last_ms = ts_ms
                _last_rand = secrets.randbits(80)
        else:
            _last_ms = ts_ms
            _last_rand = secrets.randbits(80)
        return _encode_base32(ts_ms, 10) + _encode_base32(_last_rand, 16)


def new_job_id() -> str:
    """작업 ID 생성 (ULID 기반)."""
    return new_ulid()


def new_request_id() -> str:
    """요청 ID 생성 (ULID 기반)."""
    return new_ulid()


def new_event_id() -> str:
    """이벤트 ID 생성 (ULID 기반).

    SSE payload(`event_id`) 식별자로 사용되며 발행 순서대로 단조 증가한다
    (events.md §공통 규칙 — Crockford Base32 26자).
    """
    return new_ulid()
