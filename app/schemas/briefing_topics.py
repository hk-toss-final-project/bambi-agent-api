"""아침 브리핑 주제 선정 API 스키마.

Service가 아침 생성 요청의 `topics[]`에 넣을 주제를 조회할 때 쓰는 응답 모델을
정의한다.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class BriefingPreparationStatus(StrEnum):
    """사용자·날짜별 브리핑 준비 Snapshot 상태."""

    NOT_PREPARED = "NOT_PREPARED"
    READY = "READY"


class BriefingPreparationRequest(BaseModel):
    """Service가 사용자·날짜별 아침 브리핑 준비를 요청하는 본문."""

    model_config = ConfigDict(extra="forbid")

    briefing_date: date = Field(description="아침 브리핑을 생성할 KST 기준 날짜")
    idempotency_key: str = Field(
        min_length=1,
        max_length=200,
        description="같은 사용자·날짜의 중복 준비 Job을 막는 키",
    )
    limit: int = Field(default=3, ge=1, le=5, description="미리 고를 주제 수")


class BriefingTopicsResponse(BaseModel):
    """아침 브리핑에 쓸 주제와 그 근거."""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(description="조회 대상 사용자 ID")
    preparation_status: BriefingPreparationStatus = Field(
        default=BriefingPreparationStatus.READY,
        description=(
            "NOT_PREPARED는 날짜별 Snapshot이 아직 없다는 뜻이고, READY는 "
            "topics가 비어 있어도 준비가 끝났다는 뜻이다"
        ),
    )
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
