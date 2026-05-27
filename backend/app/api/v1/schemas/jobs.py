"""T076 / T115: 작업 관련 API 요청/응답 Pydantic 스키마.

contracts/openapi.yaml의 CreateJobRequest / Job / VideoMetadata / JobListEnvelope
스키마와 매핑된다. 도메인 모델(VideoJob, VideoMetadata)을 응답 형태로 그대로 재수출한다.
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


class JobListResponse(BaseModel):
    """GET /v1/jobs 응답 바디(data 부) 스키마.

    openapi.yaml §JobListEnvelope.data 와 일치한다.

    items: VideoJob 도메인 모델의 직렬화 결과 배열.
    next_cursor: 다음 페이지 cursor (없으면 None).

    items 타입은 ``list[VideoJobResponse]`` 가 이상적이지만, 라우터에서는
    ``model_dump(mode="json")`` 결과를 직접 envelope 에 실어 보내므로 본 클래스는
    OpenAPI 스키마 문서화 용도로만 사용한다.
    """

    items: list[VideoJobResponse] = Field(default_factory=list)
    next_cursor: str | None = None
