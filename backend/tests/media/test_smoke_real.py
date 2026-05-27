"""T123: 실네트워크 e2e 스모크 테스트 (기본 SKIP).

목적:

- ``RUN_REAL_NETWORK=1`` 환경 변수가 설정된 경우에만 실행된다.
- 단일 짧은 YouTube 영상을 받아 다운로드 → 자막 추출 → (Fake) 번역 → 렌더링까지의
  파이프라인이 통합 환경에서 동작하는지 빠르게 확인한다.
- Anthropic API 호출은 비용/네트워크 의존성을 피하기 위해 ``FakeTranslationProvider`` 로
  대체한다 — 본 테스트는 **download/extract/render** 만 실제 네트워크/도구를 사용한다.

테스트 URL:

- Big Buck Bunny / Creative Commons / 그 외 안정적인 짧은 영상 1건이 필요하다.
- 현재 ``_SMOKE_URL`` 은 후일 운영자가 검증해 교체할 수 있도록 명시적 상수로 정의한다.
- URL 이 죽으면 ``yt-dlp`` 단계에서 실패한다 — 본 테스트는 환경 변수 gating 으로
  CI 기본 흐름에는 영향을 주지 않으므로 안전하다.

수동 실행 예::

    RUN_REAL_NETWORK=1 pytest tests/media/test_smoke_real.py -v -s
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# 운영자가 검증 후 교체 가능한 안정 URL. "Me at the zoo" — YouTube 최초 업로드 영상 (~19s).
# 본 영상은 공개적으로 알려진 안정적인 시연 자산이지만, 자막 가용성/지역 차단 등
# 외부 요인이 변동될 수 있으므로 테스트 운영자가 주기적으로 확인해야 한다.
_SMOKE_URL: str = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


pytestmark = [
    pytest.mark.media,
    pytest.mark.skipif(
        not os.environ.get("RUN_REAL_NETWORK"),
        reason="RUN_REAL_NETWORK=1 환경 변수가 설정되지 않아 실네트워크 스모크 테스트를 건너뜁니다.",
    ),
]


async def test_full_pipeline_produces_dual_subtitle(tmp_path: Path) -> None:
    """단일 짧은 영상에 대해 download → 자막 추출 → (Fake) 번역 → dual 파일 생성을 검증한다.

    네트워크 의존:
        - yt-dlp 가 영상 / 자막 메타데이터를 조회 / 다운로드 한다.
    네트워크 비의존:
        - 번역은 :class:`FakeTranslationProvider` 로 수행한다 (Anthropic API 호출 0건).

    실패 시 일반적 진단:
        - 401/403: 네트워크 차단 (회사 프록시 / 지역 제한)
        - 자막 없음: 본 영상에 자막이 사라졌을 가능성 → URL 교체 필요
    """
    # 지연 import — 본 모듈은 RUN_REAL_NETWORK 미설정 시 import 비용도 최소화.
    from app.core.security import parse_youtube_url
    from app.domain.media.download import download_video
    from app.domain.subtitles.dual_generator import generate_dual_srt
    from app.domain.subtitles.models import SubtitleCue
    from app.domain.subtitles.normalize import normalize_srt
    from app.domain.translation.provider import ChunkCue, TranslationChunk
    from app.infrastructure.youtube.subtitles import download_subtitles

    # 1) URL 파싱 — 잘못된 URL 이면 즉시 실패.
    video_id = parse_youtube_url(_SMOKE_URL)
    assert len(video_id) == 11

    # 2) 영상 다운로드 — 파일이 생성되고 0보다 큰 크기여야 한다.
    video_path = tmp_path / "video.mp4"
    await download_video(youtube_video_id=video_id, output_path=video_path)
    assert video_path.exists()
    assert video_path.stat().st_size > 0

    # 3) 원문 자막 다운로드 — 자막이 없는 영상이면 본 테스트는 부적합 (운영자가 URL 교체).
    subtitle_dir = tmp_path / "subs"
    subtitle_dir.mkdir()
    sub_result = await download_subtitles(
        youtube_video_id=video_id,
        output_dir=subtitle_dir,
        languages=("en", "ja", "ko"),
    )
    assert sub_result.file_path.exists(), (
        "원문 자막을 받지 못했습니다 — 본 영상에 자막이 없거나 yt-dlp 가 변경되었을 수 있습니다."
    )

    # 4) 자막 정규화 → SubtitleCue 목록
    source_cues: list[SubtitleCue] = normalize_srt(
        sub_result.file_path.read_text(encoding="utf-8")
    )
    assert len(source_cues) > 0

    # 5) Fake 번역 — Anthropic API 호출 없이 cue 텍스트만 prefix 변형.
    #    FakeTranslationProvider 는 ChunkCue 를 입력으로 받으므로 SubtitleCue → ChunkCue 어댑트.
    from tests.unit.test_translation_provider import FakeTranslationProvider

    chunk_cues = [
        ChunkCue(
            sequence=i + 1,
            start_ms=c.start_ms,
            end_ms=c.end_ms,
            text=c.text,
        )
        for i, c in enumerate(source_cues)
    ]
    chunk = TranslationChunk(
        source_lang=sub_result.language,  # type: ignore[arg-type]
        target_lang="ko",
        cues=chunk_cues,
    )
    fake = FakeTranslationProvider()
    translated_chunk = await fake.translate_chunk(chunk)
    assert len(translated_chunk.cues) == len(source_cues)

    # 번역 결과를 SubtitleCue 로 어댑트 (generate_dual_srt 는 SubtitleCue 를 요구).
    translated_cues = [
        SubtitleCue(sequence=t.sequence, start_ms=t.start_ms, end_ms=t.end_ms, text=t.text)
        for t in translated_chunk.cues
    ]

    # 6) dual SRT 생성 — 결과 파일이 존재하고 두 언어 라인이 모두 포함돼야 한다.
    dual_path = tmp_path / "dual.srt"
    dual_srt = generate_dual_srt(source_cues, translated_cues)
    dual_path.write_text(dual_srt, encoding="utf-8")
    assert dual_path.exists()
    assert dual_path.stat().st_size > 0

    # 한 cue 라도 원문 / 번역 둘 다 포함하는지 sanity check.
    contents = dual_path.read_text(encoding="utf-8")
    assert "[번역]" in contents, "FakeTranslationProvider 의 번역 라인이 dual 결과에 포함되어야 합니다."
