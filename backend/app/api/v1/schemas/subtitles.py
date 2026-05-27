"""T076: 자막 관련 API 응답 Pydantic 스키마.

contracts/openapi.yaml의 SubtitleBundle 스키마와 매핑된다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.jobs.models import Lang
from app.domain.subtitles.models import SubtitleCue


class SubtitleBundleResponse(BaseModel):
    """GET /v1/jobs/{id}/subtitles 응답 스키마.

    원문(source)과 번역(translated) 자막 큐 배열 및 페이지네이션 정보를 포함한다.
    openapi.yaml SubtitleBundle 스키마와 1:1 대응.
    """

    job_id: str = Field(description="VideoJob의 26자 ULID")
    source_language: Lang = Field(description="원문 자막 언어 코드 (ko/ja)")
    target_language: Lang = Field(description="번역 자막 언어 코드 (ko/ja)")
    source_cues: list[SubtitleCue] = Field(description="원문 자막 큐 목록 (페이지 단위)")
    translated_cues: list[SubtitleCue] = Field(description="번역 자막 큐 목록 (페이지 단위)")
    total: int = Field(description="전체 원문 큐 수 (페이지네이션 무관)")
    offset: int = Field(description="현재 페이지의 시작 오프셋")
    limit: int = Field(description="현재 페이지의 최대 큐 수")
