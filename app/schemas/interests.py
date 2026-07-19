"""사용자 관심 키워드 Profile 조회·재계산 API 스키마."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class InterestSchema(BaseModel):
    """관심 Profile API 모델의 변경 불가능한 공통 기반."""

    model_config = ConfigDict(frozen=True)


class InterestItem(InterestSchema):
    """개인 Wiki 문서에서 계산된 관심 Topic 하나."""

    interest_id: str = Field(description="관심 Topic UUID")
    topic: str = Field(description="검색과 생성에 사용할 관심 키워드")
    category: str | None = Field(default=None, description="관심 Category")
    score: float = Field(ge=-1, le=1, description="관심도 점수")
    confidence: float = Field(ge=0, le=1, description="추론 신뢰도")
    document_ids: list[str] = Field(description="관심 근거 Wiki 문서 ID")
    evidence: dict[str, object] = Field(description="점수 계산 근거")


class InterestProfileResponse(InterestSchema):
    """특정 Wiki Version에서 계산된 활성 관심 Profile."""

    feature_id: str = Field(default="INT-001", description="명세 기능 ID")
    profile_id: str = Field(description="관심 Profile UUID")
    user_id: str = Field(description="사용자 ID")
    wiki_version_id: str = Field(description="계산 기준 Wiki Build UUID")
    version: int = Field(ge=1, description="사용자별 관심 Profile Version")
    status: str = Field(description="Profile 상태")
    calculated_at: datetime = Field(description="관심 계산 시각")
    interests: list[InterestItem] = Field(description="점수순 관심 Topic 목록")


class InterestRebuildRequest(InterestSchema):
    """관심 Profile을 다시 계산하는 개발용 요청."""

    limit: int = Field(default=20, ge=1, le=100, description="저장할 최대 관심 Topic 수")
