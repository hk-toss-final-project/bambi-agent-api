"""FastAPI MVP 내부 API에서 사용하는 요청과 응답 스키마."""

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    model_validator,
)


class ImmutableSchema(BaseModel):
    """응답과 저장 레코드가 요청 처리 중 변경되지 않도록 하는 기본 모델."""

    model_config = ConfigDict(frozen=True)


class UserPlan(StrEnum):
    """MVP에서 지원하는 사용자 플랜 종류."""

    FREE = "free"
    PAID = "paid"


class JobStatus(StrEnum):
    """비동기 Agent Job의 처리 상태."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PublishStatus(StrEnum):
    """Service Worker가 전달하는 발행 처리 결과."""

    PUBLISHED = "published"
    FAILED = "failed"


class PublishBatchResultStatus(StrEnum):
    """Batch ACK 처리 후 Agent API가 확정한 항목별 결과."""

    PUBLISHED = "published"
    RETRY_SCHEDULED = "retry_scheduled"
    FAILED = "failed"


class HealthResponse(ImmutableSchema):
    """Liveness와 Readiness 상태 응답."""

    status: str = Field(description="현재 상태")
    checks: dict[str, bool] = Field(default_factory=dict, description="컴포넌트별 상태")


class VersionResponse(ImmutableSchema):
    """Agent API와 실행 환경 버전 응답."""

    name: str = Field(description="애플리케이션 이름")
    version: str = Field(description="애플리케이션 버전")
    environment: str = Field(description="실행 환경")


class UserContextUpsertRequest(ImmutableSchema):
    """Service API가 전달하는 최소 사용자 컨텍스트."""

    context_version: int = Field(ge=1, description="단조 증가하는 컨텍스트 버전")
    plan: UserPlan = Field(description="사용자 플랜")
    preferred_language: str = Field(
        default="ko", min_length=2, max_length=16, description="선호 콘텐츠 언어"
    )
    personalization_enabled: bool = Field(
        default=True, description="개인화 기능 사용 여부"
    )
    blocked_interest_ids: list[str] = Field(
        default_factory=list, description="차단한 관심사 식별자 목록"
    )
    blocked_source_ids: list[str] = Field(
        default_factory=list, description="차단한 Source 식별자 목록"
    )


class UserContextResponse(ImmutableSchema):
    """저장된 사용자 컨텍스트와 추적 정보."""

    feature_id: str = Field(default="SVC-001", description="명세 기능 ID")
    user_id: str = Field(description="사용자 식별자")
    context_version: int = Field(description="반영된 컨텍스트 버전")
    plan: UserPlan = Field(description="반영된 사용자 플랜")
    preferred_language: str = Field(description="반영된 선호 언어")
    personalization_enabled: bool = Field(description="개인화 사용 여부")
    blocked_interest_ids: list[str] = Field(description="차단 관심사 목록")
    blocked_source_ids: list[str] = Field(description="차단 Source 목록")
    updated_at: datetime = Field(description="컨텍스트 갱신 시각")
    request_id: str = Field(description="요청 추적 ID")


class WikiSourceRequestBase(ImmutableSchema):
    """개인 Wiki 원천 처리 요청의 공통 필드."""

    source_event_id: str = Field(
        min_length=1, max_length=128, description="멱등 처리를 위한 원천 이벤트 ID"
    )
    occurred_at: datetime | None = Field(
        default=None, description="사용자 행동 발생 시각"
    )
    memo: str | None = Field(default=None, max_length=4000, description="사용자 메모")


class WebClippingRequest(WikiSourceRequestBase):
    """웹 클리핑을 개인 Wiki 처리 작업으로 전달하는 요청."""

    source: HttpUrl = Field(
        validation_alias=AliasChoices("source", "url"),
        description="클리핑 원문 URL. 기존 url 필드도 입력 호환을 위해 허용",
    )
    title: str = Field(min_length=1, max_length=500, description="클리핑 제목")
    author: str | None = Field(
        default=None, max_length=500, description="원문 작성자"
    )
    published: datetime | None = Field(default=None, description="원문 게시 시각")
    created: date | None = Field(default=None, description="사용자가 클리핑한 날짜")
    description: str | None = Field(
        default=None, max_length=4000, description="원문 설명"
    )
    tags: list[str] = Field(
        default_factory=list,
        max_length=100,
        description="클리퍼가 전달한 태그 목록",
    )
    content: str = Field(min_length=1, description="Markdown 클리핑 본문")

    @property
    def url(self) -> HttpUrl:
        """기존 호출부가 사용할 수 있도록 source URL을 url 속성으로 제공한다."""
        return self.source


class UrlWikiSourceRequest(WikiSourceRequestBase):
    """사용자가 입력한 URL을 개인 Wiki 처리 작업으로 전달하는 요청."""

    url: HttpUrl = Field(description="개인 Wiki에 반영할 URL")


class ContentMarkRequest(WikiSourceRequestBase):
    """생성 콘텐츠의 위키마킹 처리를 요청하는 모델."""

    content_id: str = Field(min_length=1, max_length=128, description="생성 콘텐츠 ID")


class FeedbackSignalItem(ImmutableSchema):
    """관심사 점수에 반영할 행동 신호 한 건."""

    source_event_id: str = Field(
        min_length=1, max_length=128, description="멱등 처리를 위한 신호 이벤트 ID"
    )
    signal_type: Literal["like", "unlike", "hide", "report"] = Field(
        description="행동 유형 (가중치는 Agent가 관리)"
    )
    topics: list[str] = Field(
        min_length=1,
        max_length=10,
        description="신호가 가리키는 관심 Topic 목록 (Service가 해석해 전달)",
    )
    content_id: str | None = Field(
        default=None, max_length=128, description="행동 대상 콘텐츠 ID"
    )
    occurred_at: datetime | None = Field(
        default=None, description="행동 발생 시각 (시간 감쇠 기준)"
    )


class FeedbackSignalsRequest(ImmutableSchema):
    """행동 신호 Batch를 전달하는 요청."""

    signals: list[FeedbackSignalItem] = Field(
        min_length=1, max_length=100, description="행동 신호 목록"
    )


class FeedbackSignalsResponse(ImmutableSchema):
    """행동 신호 접수 결과."""

    user_id: str = Field(description="신호를 반영할 사용자 ID")
    accepted_count: int = Field(
        ge=0, description="신규 저장된 신호 수 (source_event_id 중복 제외)"
    )
    request_id: str = Field(description="요청 추적 ID")


class GenerationRequest(ImmutableSchema):
    """리포트 생성기 개인화 콘텐츠 생성을 요청하는 모델."""

    idempotency_key: str = Field(
        min_length=1,
        max_length=128,
        description=(
            "중복 생성을 방지하는 요청 키. Service 스케줄러는 "
            "`{schedule window}-{user_id}-{content_type}` 규칙을 권장한다."
        ),
    )
    topic: str = Field(min_length=1, max_length=500, description="생성할 콘텐츠 주제")
    content_type: str = Field(
        default="interest_news_card",
        min_length=1,
        max_length=64,
        description="생성 콘텐츠 유형",
    )
    language: str | None = Field(
        default=None, min_length=2, max_length=16, description="요청 콘텐츠 언어"
    )
    scheduled_at: datetime | None = Field(
        default=None,
        description=(
            "Worker 실행을 예약할 시각(시간대 포함). 지정하면 그 시각 전에는 "
            "Job이 Claim되지 않으며, 생략하면 즉시 실행 대상이 된다."
        ),
    )

    @model_validator(mode="after")
    def validate_scheduled_at_timezone(self) -> "GenerationRequest":
        """예약 시각이 시간대 없는 값으로 들어와 모호해지는 것을 차단한다."""
        if self.scheduled_at is not None and self.scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at은 시간대를 포함한 시각이어야 합니다.")
        return self


class AcceptedJobResponse(ImmutableSchema):
    """비동기 작업 접수 결과."""

    job_id: str = Field(description="Agent Job 식별자")
    feature_id: str = Field(description="작업을 생성한 명세 기능 ID")
    status: JobStatus = Field(description="현재 작업 상태")
    request_id: str = Field(description="요청 추적 ID")
    created_at: datetime = Field(description="작업 생성 시각")
    source_document_id: str | None = Field(
        default=None, description="원본 문서 Head 식별자"
    )
    source_document_version_id: str | None = Field(
        default=None, description="즉시 저장된 원본 문서 Version 식별자"
    )
    generation_request_id: str | None = Field(
        default=None, description="Report Builder 생성 요청 식별자"
    )


class JobStatusResponse(AcceptedJobResponse):
    """Agent Job 상태와 진행률 응답."""

    user_id: str = Field(description="작업 대상 사용자 ID")
    job_type: str = Field(description="Worker가 처리할 작업 유형")
    progress: int = Field(default=0, ge=0, le=100, description="작업 진행률")
    updated_at: datetime = Field(description="마지막 상태 변경 시각")
    error_code: str | None = Field(default=None, description="실패 오류 코드")


class JobResultResponse(ImmutableSchema):
    """완료된 Agent Job 결과 응답."""

    job_id: str = Field(description="Agent Job 식별자")
    feature_id: str = Field(description="원본 명세 기능 ID")
    status: JobStatus = Field(description="완료 작업 상태")
    result: dict[str, object] = Field(description="기능별 작업 결과")
    completed_at: datetime = Field(description="작업 완료 시각")


class CitationSchema(ImmutableSchema):
    """발행 Snapshot에 포함되는 출처 정보."""

    citation_id: str = Field(description="Citation 식별자")
    title: str = Field(description="출처 제목")
    url: str = Field(description="출처 URL")


class PublishSnapshotResponse(ImmutableSchema):
    """Service Worker가 service-db에 저장할 발행 Snapshot."""

    content_id: str = Field(description="생성 콘텐츠 식별자")
    user_id: str = Field(description="콘텐츠 대상 사용자 ID")
    version: int = Field(ge=1, description="콘텐츠 버전")
    snapshot_hash: str = Field(description="Snapshot 무결성 Hash")
    title: str = Field(description="콘텐츠 제목")
    summary: str = Field(description="피드용 콘텐츠 요약")
    body: str = Field(description="발행 콘텐츠 본문")
    citations: list[CitationSchema] = Field(
        default_factory=list, description="본문과 연결된 출처 목록"
    )
    created_at: datetime = Field(description="Snapshot 생성 시각")


class PublishBatchClaimRequest(ImmutableSchema):
    """Service Worker가 처리할 Publish Snapshot Batch를 점유하는 요청."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "worker_id": "service-worker-01",
                    "limit": 50,
                    "lease_seconds": 120,
                }
            ]
        }
    )

    worker_id: str = Field(
        min_length=1,
        max_length=128,
        description="Batch를 처리할 Service Worker Instance 식별자",
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=100,
        description="한 번에 Claim할 최대 Snapshot 수",
    )
    lease_seconds: int = Field(
        default=120,
        ge=30,
        le=600,
        description="다른 Worker의 중복 Claim을 막는 Lease 시간(초)",
    )


class PublishBatchClaimResponse(ImmutableSchema):
    """Service Worker가 점유한 Publish Snapshot Batch와 Lease 정보."""

    batch_id: str | None = Field(
        default=None, description="Claim된 항목이 있을 때 생성되는 Batch 식별자"
    )
    worker_id: str = Field(description="Batch를 Claim한 Worker 식별자")
    lease_expires_at: datetime | None = Field(
        default=None, description="Batch Lease 만료 시각"
    )
    items: list[PublishSnapshotResponse] = Field(
        default_factory=list, description="service-db에 바로 반영할 Snapshot 목록"
    )


class PublishBatchAckItemRequest(ImmutableSchema):
    """Batch에서 처리한 Snapshot 한 건의 발행 결과."""

    content_id: str = Field(
        min_length=1, max_length=128, description="생성 콘텐츠 식별자"
    )
    version: int = Field(ge=1, description="service-db에 반영한 Snapshot 버전")
    snapshot_hash: str = Field(min_length=1, description="Snapshot 무결성 Hash")
    status: PublishStatus = Field(description="service-db 반영 결과")
    retryable: bool | None = Field(
        default=None, description="실패 항목을 다시 처리할 수 있는지 여부"
    )
    failure_reason: str | None = Field(
        default=None, max_length=2000, description="비밀정보를 제외한 발행 실패 사유"
    )

    @model_validator(mode="after")
    def validate_failure(self) -> "PublishBatchAckItemRequest":
        """실패 ACK에 재시도 여부와 실패 사유가 포함되었는지 검증한다."""
        if self.status is PublishStatus.FAILED:
            if self.retryable is None:
                raise ValueError("발행 실패 시 retryable이 필요합니다.")
            if not self.failure_reason:
                raise ValueError("발행 실패 시 failure_reason이 필요합니다.")
        return self


class PublishBatchAckRequest(ImmutableSchema):
    """Service Worker가 전달하는 Publish Snapshot Batch 처리 결과."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "worker_id": "service-worker-01",
                    "items": [
                        {
                            "content_id": "mock-content-001",
                            "version": 1,
                            "snapshot_hash": "d3b07384d113edec49eaa6238ad5ff00d3b07384d113edec49eaa6238ad5ff00",
                            "status": "published",
                        },
                        {
                            "content_id": "mock-content-002",
                            "version": 1,
                            "snapshot_hash": "4e07408562bedb8b60ce05c1decfe3ad16b72230967de01f640b7e4729b49fce",
                            "status": "failed",
                            "retryable": True,
                            "failure_reason": "service-db timeout",
                        },
                    ],
                }
            ]
        }
    )

    worker_id: str = Field(
        min_length=1,
        max_length=128,
        description="Claim 요청과 동일한 Service Worker 식별자",
    )
    items: list[PublishBatchAckItemRequest] = Field(
        min_length=1, max_length=100, description="처리가 끝난 항목별 ACK 목록"
    )

    @model_validator(mode="after")
    def validate_unique_items(self) -> "PublishBatchAckRequest":
        """같은 콘텐츠 버전이 한 요청에 중복 포함되지 않도록 검증한다."""
        keys = [(item.content_id, item.version) for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("Batch ACK 항목의 content_id와 version은 중복될 수 없습니다.")
        return self


class PublishBatchAckItemResponse(ImmutableSchema):
    """Agent API가 확정한 Batch ACK 항목별 처리 결과."""

    content_id: str = Field(description="생성 콘텐츠 식별자")
    version: int = Field(description="처리한 Snapshot 버전")
    result: PublishBatchResultStatus = Field(description="Agent API 반영 결과")


class PublishBatchAckResponse(ImmutableSchema):
    """Publish Snapshot Batch의 부분 성공 ACK 결과."""

    batch_id: str = Field(description="ACK 대상 Batch 식별자")
    published_count: int = Field(ge=0, description="발행 완료 항목 수")
    retry_scheduled_count: int = Field(ge=0, description="재시도 예약 항목 수")
    failed_count: int = Field(ge=0, description="최종 실패 항목 수")
    results: list[PublishBatchAckItemResponse] = Field(
        description="요청 순서를 유지한 항목별 처리 결과"
    )
    acknowledged_at: datetime = Field(description="Batch ACK 반영 시각")


class PublishAckRequest(ImmutableSchema):
    """Service Worker가 전달하는 발행 완료 또는 실패 ACK."""

    version: int = Field(ge=1, description="반영한 콘텐츠 버전")
    snapshot_hash: str = Field(min_length=1, description="반영한 Snapshot Hash")
    status: PublishStatus = Field(description="service-db 반영 결과")
    failure_reason: str | None = Field(
        default=None, max_length=2000, description="발행 실패 사유"
    )

    @model_validator(mode="after")
    def validate_failure_reason(self) -> "PublishAckRequest":
        """발행 실패 ACK에 실패 사유가 포함되었는지 검증한다."""
        if self.status is PublishStatus.FAILED and not self.failure_reason:
            raise ValueError("발행 실패 시 failure_reason이 필요합니다.")
        return self


class PublishAckResponse(ImmutableSchema):
    """Agent API가 ACK를 반영한 결과."""

    feature_id: str = Field(default="SW-009", description="명세 기능 ID")
    content_id: str = Field(description="생성 콘텐츠 식별자")
    version: int = Field(description="반영된 콘텐츠 버전")
    status: PublishStatus = Field(description="반영된 발행 상태")
    acknowledged_at: datetime = Field(description="ACK 반영 시각")
