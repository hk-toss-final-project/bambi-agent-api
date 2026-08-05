"""Service가 전달하는 관심사 taxonomy Snapshot API 스키마."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.mvp import TaxonomyId


class ImmutableSchema(BaseModel):
    """요청 처리 중 변경되지 않는 taxonomy 계약 기본 모델."""

    model_config = ConfigDict(frozen=True)


class InterestTaxonomyTopic(ImmutableSchema):
    """Agent 수집 대상 하나가 되는 taxonomy Topic."""

    id: TaxonomyId
    name: str = Field(min_length=1, max_length=100)
    name_en: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    order: int = Field(ge=0)
    keywords: list[str] = Field(default_factory=list, max_length=30)


class InterestTaxonomyCategory(ImmutableSchema):
    """하위 Topic을 포함한 taxonomy Category."""

    id: TaxonomyId
    name: str = Field(min_length=1, max_length=100)
    name_en: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    emoji: str = Field(min_length=1, max_length=20)
    order: int = Field(ge=0)
    topics: list[InterestTaxonomyTopic] = Field(min_length=1, max_length=30)


class InterestTaxonomyUpsertRequest(ImmutableSchema):
    """Service DB의 활성 taxonomy 전체 Snapshot."""

    version: str = Field(min_length=1, max_length=50)
    source_hash: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    locale: str = Field(min_length=2, max_length=16)
    categories: list[InterestTaxonomyCategory] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "InterestTaxonomyUpsertRequest":
        """Category와 Topic 안정 ID가 Snapshot 안에서 중복되지 않게 한다."""
        category_ids = [category.id for category in self.categories]
        topic_ids = [topic.id for category in self.categories for topic in category.topics]
        if len(category_ids) != len(set(category_ids)):
            raise ValueError("Category ID가 중복되었습니다.")
        if len(topic_ids) != len(set(topic_ids)):
            raise ValueError("Topic ID가 중복되었습니다.")
        return self


class InterestTaxonomyResponse(ImmutableSchema):
    """Agent DB에 저장한 taxonomy Snapshot 요약."""

    version: str
    source_hash: str
    category_count: int
    topic_count: int
