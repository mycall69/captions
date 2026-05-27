"""T076: 작업 관련 API 요청/응답 Pydantic 스키마.

contracts/openapi.yaml의 CreateJobRequest / Job / VideoMetadata 스키마와 매핑된다.
도메인 모델(VideoJob, VideoMetadata)을 응답 형태로 그대로 재수출한다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# 응답 스키마는 도메인 모델을 직접 재수출 (openapi.yaml과 1:1 대응)
from app.domain.jobs.models import VideoJob as VideoJobResponse  # noqa: F401
from app.domain.jobs.models import VideoMetadata as VideoMetadataResponse  # noqa: F401


class CreateJobRequest(BaseModel):
    """POST /v1/jobs 요청 바디 스키마.

    url: 처리할 YouTube 영상 URL (비어있지 않은 문자열).
    """

    url: str = Field(min_length=1, description="처리할 YouTube 영상 URL")
