"""최신 외부 정보 검색 개발 API의 요청·응답 스키마."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

LatestProviderName = Literal["naver", "newsapi", "gdelt", "google_news"]


class LatestInformationSchema(BaseModel):
    """최신 정보 API 모델의 변경 불가능한 공통 기반."""

    model_config = ConfigDict(frozen=True)


class LatestInformationSearchRequest(LatestInformationSchema):
    """직접 키워드 또는 활성 관심 Profile로 최신 자료를 검색하는 요청."""

    keywords: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="비어 있으면 활성 관심 키워드 상위 항목 사용",
    )
    providers: list[LatestProviderName] = Field(
        default_factory=lambda: ["gdelt"],
        min_length=1,
        max_length=3,
        description="검색할 외부 Provider 목록",
    )
    language: str | None = Field(
        default=None, min_length=2, max_length=16, description="검색 언어"
    )
    limit_per_provider: int = Field(
        default=10, ge=1, le=50, description="Provider별 최대 결과 수"
    )

    @model_validator(mode="after")
    def validate_unique_values(self) -> "LatestInformationSearchRequest":
        """빈 키워드와 중복 Provider를 정리하지 않고 명확한 검증 오류로 차단한다."""
        if any(not keyword.strip() for keyword in self.keywords):
            raise ValueError("keywords에는 빈 문자열을 넣을 수 없습니다.")
        if len(self.providers) != len(set(self.providers)):
            raise ValueError("providers는 중복될 수 없습니다.")
        return self


class LatestInformationItem(LatestInformationSchema):
    """Global 수집 캐시에 저장된 정규화 최신 문서 한 건."""

    provider: LatestProviderName = Field(description="수집 Provider")
    title: str = Field(description="기사 제목")
    url: str = Field(description="원문 URL")
    description: str = Field(description="기사 설명 또는 Snippet")
    published_at: datetime | None = Field(default=None, description="게시 시각")
    source_name: str | None = Field(default=None, description="언론사·Domain")
    language: str | None = Field(default=None, description="기사 언어")
    document_id: str = Field(description="Global 수집 캐시 문서 UUID")
    created: bool = Field(description="이번 검색에서 캐시에 새로 저장했는지 여부")


class LatestProviderFailure(LatestInformationSchema):
    """부분 실패한 외부 Provider와 안전한 오류 정보."""

    provider: LatestProviderName = Field(description="실패한 Provider")
    error_code: str = Field(description="Provider 오류 코드")
    message: str = Field(description="비밀정보를 제외한 실패 메시지")


class LatestInformationSearchResponse(LatestInformationSchema):
    """키워드와 Provider별 최신 정보 수집·저장 결과."""

    feature_id: str = Field(default="REPORT-005", description="명세 기능 ID")
    user_id: str = Field(description="검색 기준 사용자 ID")
    query: str = Field(description="Provider에 전달한 검색 Query")
    keywords: list[str] = Field(description="사용한 관심 또는 직접 입력 키워드")
    items: list[LatestInformationItem] = Field(description="저장된 최신 Global 문서")
    provider_failures: list[LatestProviderFailure] = Field(
        default_factory=list, description="부분 실패 Provider 목록"
    )
