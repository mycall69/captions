"""T055: SubtitleCue, SubtitleTrack Pydantic 도메인 모델.

contracts/openapi.yaml의 SubtitleCue / SubtitleBundle 스키마 및
data-model.md의 subtitle_track / subtitle_cue 정의와 일치해야 한다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.domain.jobs.models import Lang  # canonical — 여기서 재수출

__all__ = [
    "Lang",
    "SubtitleKind",
    "SubtitleOrigin",
    "SubtitleFormat",
    "SubtitleCue",
    "SubtitleTrack",
]

SubtitleKind = Literal["source", "translated"]
SubtitleOrigin = Literal["manual", "auto", "generated"]
SubtitleFormat = Literal["srt", "vtt"]


class SubtitleCue(BaseModel):
    """단일 자막 큐 — 시퀀스 번호, 타임스탬프, 본문 텍스트를 포함한다.

    openapi.yaml SubtitleCue 스키마와 1:1 대응.
    """

    sequence: int = Field(ge=1)
    """트랙 내 1-based 순서 번호."""

    start_ms: int = Field(ge=0)
    """큐 시작 시각 (밀리초)."""

    end_ms: int
    """큐 종료 시각 (밀리초, start_ms 초과 필요)."""

    text: str
    """정규화된 자막 본문 (개행 LF)."""

    @model_validator(mode="after")
    def _check_range(self) -> SubtitleCue:
        """end_ms > start_ms 불변식 검증."""
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class SubtitleTrack(BaseModel):
    """자막 트랙 — 단일 언어의 전체 큐 목록과 메타데이터.

    data-model.md subtitle_track 정의와 1:1 대응.
    """

    id: str = Field(min_length=26, max_length=26)
    """26자 ULID 트랙 식별자."""

    job_id: str = Field(min_length=26, max_length=26)
    """소속 VideoJob의 26자 ULID."""

    kind: SubtitleKind
    """트랙 종류: 'source'(원문) 또는 'translated'(번역)."""

    language: Lang
    """트랙 언어 코드."""

    origin: SubtitleOrigin
    """트랙 생성 방식: 'manual' | 'auto' | 'generated'."""

    source_format: SubtitleFormat | None = None
    """원본 파일 형식 (SRT/VTT). 수동 업로드 시 설정."""

    file_path: str | None = None
    """스토리지 내 파일 경로."""

    cue_count: int = 0
    """저장된 큐 총 수."""

    cues: list[SubtitleCue] = Field(default_factory=list)
    """인메모리 큐 목록 (저장 시 별도 테이블로 분리)."""
