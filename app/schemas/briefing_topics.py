"""아침 브리핑 주제 선정 API 스키마.

Service가 아침 생성 요청의 `topics[]`에 넣을 주제를 조회할 때 쓰는 응답 모델을
정의한다.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class BriefingTopicsResponse(BaseModel):
    """아침 브리핑에 쓸 주제와 그 근거."""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(description="조회 대상 사용자 ID")
    topics: list[str] = Field(
        default_factory=list,
        description=(
            "고른 주제 이름. **순서가 곧 리포트 섹션 순서**다. "
            "비어 있으면 Service는 아침 생성 요청을 보내지 않는다"
        ),
    )
    reason: str = Field(
        default="", description="왜 이 조합을 골랐는지. 로그·디버깅용이며 사용자에게 보이지 않는다"
    )
    candidate_count: int = Field(
        default=0, description="선정자가 실제로 검토한 후보 수"
    )
