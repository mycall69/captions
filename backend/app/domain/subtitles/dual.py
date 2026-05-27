"""T057 별칭 모듈 — dual_generator.py 재수출.

테스트는 app.domain.subtitles.dual_generator를 직접 임포트하며,
이 모듈은 편의 별칭으로 제공된다.
"""

from app.domain.subtitles.dual_generator import (  # noqa: F401
    generate_dual_srt,
    generate_dual_vtt,
)
