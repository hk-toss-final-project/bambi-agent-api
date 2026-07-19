"""Bambi 생성 콘텐츠 후보 목록·상세 조회 API 스키마."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GeneratedContentSchema(BaseModel):
    """생성 콘텐츠 조회 모델의 변경 불가능한 공통 기반."""

    model_config = ConfigDict(frozen=True)


class GeneratedContentSummary(GeneratedContentSchema):
    """사용자 생성 콘텐츠 목록 한 항목."""

    candidate_id: str = Field(description="생성 후보 UUID")
    content_id: str = Field(description="서비스에서 사용하는 콘텐츠 ID")
    version: int = Field(ge=1, description="콘텐츠 Version")
    content_type: str = Field(description="콘텐츠 유형")
    status: str = Field(description="생성 후보 상태")
    title: str = Field(description="콘텐츠 제목")
    summary: str = Field(description="피드용 요약")
    created_at: datetime = Field(description="생성 시각")


class GeneratedContentListResponse(GeneratedContentSchema):
    """사용자별 생성 콘텐츠 후보 목록."""

    feature_id: str = Field(default="BAMBI-018", description="명세 기능 ID")
    user_id: str = Field(description="사용자 ID")
    total: int = Field(ge=0, description="필터 조건에 맞는 전체 후보 수")
    items: list[GeneratedContentSummary] = Field(description="최신순 생성 후보")


class GeneratedContentCitation(GeneratedContentSchema):
    """생성 콘텐츠가 실제 참조한 Wiki 또는 Global 문서 근거."""

    citation_id: str = Field(description="Citation UUID")
    ordinal: int = Field(ge=0, description="Citation 표시 순서")
    reference: str | None = Field(default=None, description="본문의 P1·G1 참조")
    document_version_id: str | None = Field(default=None, description="근거 문서 Version UUID")
    chunk_id: str | None = Field(default=None, description="근거 Chunk UUID")
    title: str = Field(description="근거 제목")
    url: str | None = Field(default=None, description="외부 근거 URL")
    quoted_text: str | None = Field(default=None, description="생성에 사용한 근거 일부")


class GeneratedContentDetailResponse(GeneratedContentSummary):
    """본문, Citation과 실행 Metadata를 포함한 생성 콘텐츠 상세."""

    feature_id: str = Field(default="BAMBI-018", description="명세 기능 ID")
    user_id: str = Field(description="사용자 ID")
    body: str = Field(description="Markdown 콘텐츠 본문")
    structured_body: dict[str, object] = Field(description="구조화 본문 Metadata")
    snapshot_hash: str = Field(description="발행 Snapshot Hash")
    generation_request_id: str = Field(description="생성 요청 UUID")
    generation_run_id: str = Field(description="생성 실행 UUID")
    latency_ms: int | None = Field(default=None, ge=0, description="LLM 생성 지연시간")
    citations: list[GeneratedContentCitation] = Field(description="본문 근거 목록")
