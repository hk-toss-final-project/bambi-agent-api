"""FastAPI MVP 내부 API에서 사용하는 요청과 응답 스키마."""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)


class ImmutableSchema(BaseModel):
    """응답과 저장 레코드가 요청 처리 중 변경되지 않도록 하는 기본 모델."""

    model_config = ConfigDict(frozen=True)


class UserPlan(StrEnum):
    """MVP에서 지원하는 사용자 플랜 종류."""

    FREE = "free"
    PAID = "paid"


TaxonomyId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9_-]+$",
        description="Service 관심사 분류체계의 안정 ID",
    ),
]


class JobStatus(StrEnum):
    """비동기 Agent Job의 처리 상태."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING_PROVIDER = "waiting_provider"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GenerationExecutionMode(StrEnum):
    """Report 생성 결과가 필요한 시간에 따른 실행 방식."""

    SYNC = "sync"
    BATCH = "batch"


class PublishStatus(StrEnum):
    """Service Worker가 전달하는 발행 처리 결과."""

    PUBLISHED = "published"
    FAILED = "failed"


class PublishBatchResultStatus(StrEnum):
    """Batch ACK 처리 후 Agent API가 확정한 항목별 결과."""

    PUBLISHED = "published"
    RETRY_SCHEDULED = "retry_scheduled"
    FAILED = "failed"


class GenerationScope(StrEnum):
    """Report Builder가 검색 범위를 해석하는 방식."""

    SINGLE_TOPIC = "SINGLE_TOPIC"
    INTEREST_BUNDLE = "INTEREST_BUNDLE"
    WIKI_BRIEFING = "WIKI_BRIEFING"


class HealthResponse(ImmutableSchema):
    """Liveness와 Readiness 상태 응답."""

    status: str = Field(description="현재 상태")
    checks: dict[str, bool] = Field(default_factory=dict, description="컴포넌트별 상태")


class VersionResponse(ImmutableSchema):
    """Agent API와 실행 환경 버전 응답."""

    name: str = Field(description="애플리케이션 이름")
    version: str = Field(description="애플리케이션 버전")
    environment: str = Field(description="실행 환경")


class SignupInterest(ImmutableSchema):
    """회원가입 시 사용자가 고른 관심 카테고리와 그 하위 토픽 묶음.

    카테고리만 선택하고 세부 토픽은 고르지 않을 수 있으므로 `topics`는 비어 있을 수
    있다. 내부 관심사 모델(`user_interests`)의 `(category, topic)` 쌍으로 확장된다.
    """

    category: str | None = Field(
        default=None,
        max_length=100,
        description="가입 시 선택한 관심 카테고리. 사용자 추가 Topic이면 null",
    )
    topics: list[str] = Field(
        default_factory=list,
        description="카테고리 하위로 선택한 관심 토픽 목록 (선택 사항)",
    )


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
    interest_taxonomy_version: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
        description="선택 Category·Topic ID를 해석할 관심사 분류체계 버전",
    )
    selected_category_ids: list[TaxonomyId] = Field(
        default_factory=list,
        max_length=8,
        description="온보딩에서 선택한 Category 안정 ID 목록",
    )
    selected_topic_ids: list[TaxonomyId] = Field(
        default_factory=list,
        max_length=12,
        description="온보딩에서 선택한 Topic 안정 ID 목록",
    )
    blocked_interest_ids: list[str] = Field(
        default_factory=list, description="차단한 관심사 식별자 목록"
    )
    blocked_source_ids: list[str] = Field(
        default_factory=list, description="차단한 Source 식별자 목록"
    )
    signup_interests: list[SignupInterest] = Field(
        default_factory=list,
        description="회원가입 시 선택한 관심 카테고리·토픽 목록 (콜드스타트 관심사 시드)",
    )
    onboarding_reports_managed_by_service: bool = Field(
        default=False,
        description=(
            "Service API가 온보딩 리포트 생성·멱등성·펜딩 상태를 관리하는지 여부"
        ),
    )

    @model_validator(mode="after")
    def validate_interest_taxonomy_version(self) -> "UserContextUpsertRequest":
        """Category·Topic 선택이 있으면 이를 해석할 분류체계 버전을 요구한다."""
        if (
            self.selected_category_ids or self.selected_topic_ids
        ) and self.interest_taxonomy_version is None:
            raise ValueError("선택한 Category·Topic에는 interest_taxonomy_version이 필요합니다.")
        return self


class UserContextResponse(ImmutableSchema):
    """저장된 사용자 컨텍스트와 추적 정보."""

    feature_id: str = Field(default="SVC-001", description="명세 기능 ID")
    user_id: str = Field(description="사용자 식별자")
    context_version: int = Field(description="반영된 컨텍스트 버전")
    plan: UserPlan = Field(description="반영된 사용자 플랜")
    preferred_language: str = Field(description="반영된 선호 언어")
    personalization_enabled: bool = Field(description="개인화 사용 여부")
    interest_taxonomy_version: str | None = Field(
        description="반영된 관심사 분류체계 버전"
    )
    selected_category_ids: list[str] = Field(description="반영된 Category 선택 목록")
    selected_topic_ids: list[str] = Field(description="반영된 Topic 선택 목록")
    blocked_interest_ids: list[str] = Field(description="차단 관심사 목록")
    blocked_source_ids: list[str] = Field(description="차단 Source 목록")
    signup_interests: list[SignupInterest] = Field(
        default_factory=list, description="반영된 회원가입 관심 카테고리·토픽 목록"
    )
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


class ContentMarkDeletionRequest(WikiSourceRequestBase):
    """북마크 원본 연결을 해제하고 개인 Wiki 재구성을 요청하는 모델."""

    marked_source_event_id: str = Field(
        min_length=1,
        max_length=128,
        description="북마크 저장 때 사용한 source_event_id",
    )
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
    metadata: dict[str, object] = Field(
        default_factory=dict,
        description="Service가 계측한 신호 부가 정보 (해석하거나 손실시키지 않고 보존)",
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


class WikiSourceDeletionRequest(WikiSourceRequestBase):
    """개인 Wiki 문서 삭제를 요청하는 모델."""

    document_id: str = Field(
        min_length=1, max_length=128, description="삭제할 Wiki 문서 ID"
    )


class WikiDocumentDeletionResponse(ImmutableSchema):
    """Wiki 문서 삭제 반영 결과."""

    user_id: str = Field(description="문서를 삭제한 사용자 ID")
    document_id: str = Field(description="삭제된 Wiki 문서 ID")
    document_kind: str = Field(description="삭제된 문서 종류 (entity·concept 등)")
    document_key: str = Field(description="삭제된 문서 키")
    already_deleted: bool = Field(
        description="이미 삭제된 문서에 대한 멱등 재요청이었는지"
    )
    unsearchable_chunk_count: int = Field(
        ge=0, description="검색에서 제외 처리된 Chunk 수"
    )
    request_id: str = Field(description="요청 추적 ID")


class PersonalWikiResetResponse(ImmutableSchema):
    """개인 LLM Wiki 계정 단위 초기화 결과."""

    user_id: str = Field(description="Wiki를 초기화한 사용자 ID")
    reset_document_count: int = Field(ge=0, description="비활성화한 Wiki 문서 수")
    reset_relation_count: int = Field(ge=0, description="비활성화한 Wiki 관계 수")
    unsearchable_chunk_count: int = Field(
        ge=0, description="검색에서 제외한 Wiki Chunk 수"
    )
    deleted_source_document_count: int = Field(
        ge=0, description="영구 삭제한 사용자 원본 문서 수"
    )
    deleted_source_version_count: int = Field(
        ge=0, description="영구 삭제한 사용자 원본 Version 수"
    )
    redacted_source_event_count: int = Field(
        ge=0, description="개인정보 Payload를 비식별화한 Source Event 수"
    )
    retired_wiki_version_count: int = Field(
        ge=0, description="종료한 Wiki Build Snapshot 수"
    )
    retired_interest_profile_count: int = Field(
        ge=0, description="종료한 관심사 Profile 수"
    )
    cancelled_job_count: int = Field(ge=0, description="취소한 Wiki Build Job 수")
    reset_at: datetime = Field(description="초기화 완료 시각")
    request_id: str = Field(description="요청 추적 ID")


# 한 리포트가 묶을 수 있는 주제 수 상한. 주제마다 조사(검색·수집)를 따로 돌리므로
# 개수가 곧 생성 시간이다. Worker lease(600초) 안에 끝나야 같은 Job이 죽은 것으로
# 판정돼 재실행되지 않는다.
_MAX_REPORT_TOPICS = 5


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
    generation_scope: GenerationScope = Field(
        default=GenerationScope.SINGLE_TOPIC,
        description=(
            "검색 범위. SINGLE_TOPIC은 요청 topic·topics를 사용하고, "
            "INTEREST_BUNDLE은 활성 LLM Wiki 관심사와 연결 노드 묶음을 사용하며, "
            "WIKI_BRIEFING은 날짜별 개인 Wiki 주제를 준비한 뒤 사용한다."
        ),
    )
    interest_id: UUID | None = Field(
        default=None,
        description="INTEREST_BUNDLE에서 사용할 현재 활성 관심사 UUID",
    )
    topic: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description=(
            "생성할 콘텐츠 주제. SINGLE_TOPIC에서는 필수이며, "
            "INTEREST_BUNDLE에서는 활성 관심사의 루트 키워드로 결정된다."
        ),
    )
    topics: list[str] = Field(
        default_factory=list,
        max_length=_MAX_REPORT_TOPICS,
        description=(
            "한 리포트가 함께 다룰 주제 목록. 아침 요약처럼 상위 관심사 여러 개를 "
            "한 장에 묶을 때 사용한다. 비워 두면 topic 하나만 다루는 기존 동작이다. "
            "주면 topic은 카드 제목·generation_topic으로만 쓰이고, 본문이 다루는 "
            "주제는 이 목록이 된다. 주제마다 근거를 따로 모으므로 개수에 비례해 "
            f"생성 시간이 늘어난다(최대 {_MAX_REPORT_TOPICS}개)."
        ),
    )
    content_type: str = Field(
        default="interest_news_card",
        min_length=1,
        max_length=64,
        description="생성 콘텐츠 유형",
    )
    report_type: str = Field(
        default="",
        max_length=64,
        description=(
            "이 리포트가 만들어진 맥락 구분 (예: MORNING_BRIEFING, ON_DEMAND). "
            "값의 정의는 Service가 소유하며 Agent는 해석하지 않고 그대로 "
            "Publish Snapshot에 실어 돌려준다."
        ),
    )
    briefing_date: date | None = Field(
        default=None,
        description=(
            "REPORT-022가 준비한 날짜별 주제·근거 Snapshot을 재사용할 KST 날짜. "
            "아침 브리핑 외 요청은 생략한다."
        ),
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
    change_history_enabled: bool = Field(
        default=False,
        description=(
            "변경점(Delta) 추적 사용 여부. 켜면 직전 보고서 이후의 신규·갱신 "
            "사실을 갈라 정리한 통합 보고서를 만든다(기존 생성 경로를 대체). "
            "기본값은 꺼짐이며, 꺼진 요청은 지금까지와 동일하게 처리된다. "
            "응답 스키마와 발행 Payload는 켜든 끄든 같다."
        ),
    )
    execution_mode: GenerationExecutionMode = Field(
        default=GenerationExecutionMode.SYNC,
        description=(
            "sync는 기존 즉시 Worker 생성, batch는 접수 시 고정한 DB Context로 "
            "OpenAI 24시간 비동기 Batch를 사용한다."
        ),
    )

    @field_validator("topics", mode="after")
    @classmethod
    def normalize_topics(cls, value: list[str]) -> list[str]:
        """공백뿐인 주제를 버리고 중복을 합쳐 조사 횟수를 낭비하지 않게 한다.

        주제 하나가 조사 한 번(검색·수집)이라, 같은 주제가 두 번 들어오면
        같은 검색을 두 번 돌리고 근거도 중복으로 쌓인다. 대소문자만 다른
        표기는 같은 주제로 본다.
        """
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in value:
            topic = raw.strip()
            if not topic:
                continue
            if len(topic) > 500:
                raise ValueError("topics의 각 주제는 500자를 넘을 수 없습니다.")
            marker = topic.casefold()
            if marker in seen:
                continue
            seen.add(marker)
            normalized.append(topic)
        return normalized

    @model_validator(mode="after")
    def validate_generation_scope(self) -> "GenerationRequest":
        """범위별 필수 식별자를 확인하고 서로 다른 입력 방식을 섞지 않게 한다."""
        if self.generation_scope is GenerationScope.INTEREST_BUNDLE:
            if self.interest_id is None:
                raise ValueError("INTEREST_BUNDLE에는 interest_id가 필요합니다.")
            if self.topics:
                raise ValueError("INTEREST_BUNDLE에서는 topics를 함께 보낼 수 없습니다.")
            return self
        if self.generation_scope is GenerationScope.WIKI_BRIEFING:
            if self.briefing_date is None:
                raise ValueError("WIKI_BRIEFING에는 briefing_date가 필요합니다.")
            if self.interest_id is not None:
                raise ValueError("WIKI_BRIEFING에서는 interest_id를 보낼 수 없습니다.")
            if self.topics:
                raise ValueError("WIKI_BRIEFING에서는 topics를 미리 보낼 수 없습니다.")
            if self.topic is None or not self.topic.strip():
                raise ValueError("WIKI_BRIEFING에는 카드 제목용 topic이 필요합니다.")
            return self
        if self.topic is None or not self.topic.strip():
            raise ValueError("SINGLE_TOPIC에는 topic이 필요합니다.")
        return self

    @model_validator(mode="after")
    def validate_scheduled_at_timezone(self) -> "GenerationRequest":
        """예약 시각이 시간대 없는 값으로 들어와 모호해지는 것을 차단한다."""
        if self.scheduled_at is not None and self.scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at은 시간대를 포함한 시각이어야 합니다.")
        return self

    @model_validator(mode="after")
    def validate_execution_mode(self) -> "GenerationRequest":
        """Batch가 지원하지 않는 변경점 추적·다중 주제 요청을 접수 전에 차단한다."""
        if self.execution_mode is GenerationExecutionMode.BATCH:
            if self.generation_scope is GenerationScope.WIKI_BRIEFING:
                raise ValueError("batch 실행은 WIKI_BRIEFING을 지원하지 않습니다.")
            if self.change_history_enabled:
                raise ValueError("batch 실행은 change_history_enabled를 지원하지 않습니다.")
            if self.topics:
                raise ValueError("batch 실행은 다중 topics를 지원하지 않습니다.")
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


class JobStatusBatchRequest(ImmutableSchema):
    """Service Worker가 한 번에 조회할 Agent Job 식별자 목록."""

    job_ids: list[str] = Field(
        min_length=1,
        max_length=100,
        description="중복 없는 Agent Job 식별자 목록",
    )

    @field_validator("job_ids")
    @classmethod
    def validate_unique_job_ids(cls, value: list[str]) -> list[str]:
        """UUID 형식을 확인하고 같은 Job의 Batch 중복 조회를 막는다."""
        try:
            for job_id in value:
                UUID(job_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("job_ids에는 UUID 형식의 Agent Job ID만 넣을 수 있습니다.") from exc
        if len(value) != len(set(value)):
            raise ValueError("job_ids에는 중복된 Agent Job ID를 넣을 수 없습니다.")
        return value


class JobStatusBatchResponse(ImmutableSchema):
    """Agent Job Batch 상태와 조회되지 않은 식별자 목록."""

    items: list[JobStatusResponse] = Field(description="조회된 Job 상태 목록")
    missing_job_ids: list[str] = Field(
        default_factory=list,
        description="Agent DB에서 찾지 못한 Job 식별자 목록",
    )


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


class ReportCoverImageSchema(ImmutableSchema):
    """리포트 상단 대표 이미지와 원문 출처."""

    url: str = Field(description="원문에서 수집·검증한 대표 이미지 HTTPS URL")
    source_url: str = Field(description="이미지가 연결된 실제 인용 출처 URL")
    source_title: str = Field(description="화면 출처 표시에 사용할 원문 제목")
    reference: str = Field(description="대표 이미지가 연결된 Citation 참조(P/G/L)")


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
    cover_image: ReportCoverImageSchema | None = Field(
        default=None,
        description=(
            "실제 인용 출처 중 IMG-013이 결정론적으로 고른 리포트 상단 이미지. "
            "적합한 이미지가 없거나 구 Snapshot이면 null"
        ),
    )
    generation_topic: str = Field(
        default="",
        description="생성 요청의 원본 주제. 이 리포트가 왜 만들어졌는지를 남긴다.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="카드에 노출할 관심사 태그 목록 (생성 요청 topic)",
    )
    content_tags: list[str] = Field(
        default_factory=list,
        description=(
            "생성된 리포트 내용에서 뽑은 검색·추천용 태그 (REPORT-010). "
            "요청 주제와 실제 작성된 내용이 다를 수 있어 분리해 보존한다."
        ),
    )
    report_type: str = Field(
        default="",
        description=(
            "생성 요청에서 받은 맥락 구분을 그대로 돌려준다 "
            "(예: MORNING_BRIEFING, ON_DEMAND). 요청과 결과 수령 시점이 떨어져 "
            "있어, Service가 Claim 시점에 이 카드가 어떤 맥락에서 만들어졌는지 "
            "다시 짜맞추지 않도록 함께 싣는다."
        ),
    )
    request_idempotency_key: str = Field(
        default="",
        description=(
            "생성 요청의 `idempotency_key`를 원문 그대로 돌려준다 "
            "(2026-08-06 협의). Service는 이 값으로 대기 중이던 "
            "`generation_pendings` 행과 Claim으로 들어온 완료 카드를 연결한다. "
            "Agent는 해석하지 않으며, UUID 파생 등 가공은 Service가 소유한다."
        ),
    )
    generation_scope: GenerationScope = Field(
        default=GenerationScope.SINGLE_TOPIC,
        description="리포트가 단일 주제 또는 활성 관심사 범주로 생성됐는지",
    )
    source_interest_id: str = Field(
        default="",
        description="INTEREST_BUNDLE 생성의 원천이 된 활성 관심사 UUID",
    )
    interest_profile_id: str = Field(
        default="",
        description="관심사 묶음을 확정한 활성 Profile UUID",
    )
    bundle_keywords: list[str] = Field(
        default_factory=list,
        description="루트 관심사부터 시작하는 범주 검색 키워드 스냅샷",
    )
    taxonomy_topic_ids: list[str] = Field(
        default_factory=list,
        description=(
            "이 카드가 매핑되는 관심사 taxonomy Topic Key 목록 (2026-08-11 계약). "
            "Service가 뷰어 관심사와의 교집합으로 추천 피드를 만든다. "
            "인용한 Global 수집 문서의 수집 대상에서 파생하고, 없으면 요청 주제 "
            "이름으로 찾는다. **둘 다 못 찾으면 빈 목록이며 그것은 오류가 아니다** "
            "— 개인 Wiki만 인용했거나 taxonomy 밖 주제인 카드가 여기 해당한다."
        ),
    )
    taxonomy_version: str = Field(
        default="",
        description=(
            "위 topic_id들을 풀 taxonomy 버전. topic_ids가 비면 함께 빈 문자열이다 "
            "— 버전과 id가 따로 노는 값은 내보내지 않는다."
        ),
    )
    change_history_enabled: bool = Field(
        default=False,
        description=(
            "생성 요청의 `change_history_enabled` 토글을 그대로 돌려준다. "
            "true면 body가 '변경사항 → 내용 → 시사점 → "
            "타임라인' 4단 구조를 따르며, 갱신 팩트는 `- (기존) ~~값~~` / "
            "`  (변경) \\`값\\`` 두 줄로, 신규 팩트는 `- 문장 [L1]` 한 줄로 나온다. "
            "false면 지금까지와 같은 자유 형식 본문이다. Service는 이 값으로 "
            "body의 렌더링 규칙을 고르며, 본문 헤더 문자열을 파싱해 추측하지 "
            "않는다."
        ),
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
                            "content_id": "example-content-001",
                            "version": 1,
                            "snapshot_hash": "d3b07384d113edec49eaa6238ad5ff00d3b07384d113edec49eaa6238ad5ff00",
                            "status": "published",
                        },
                        {
                            "content_id": "example-content-002",
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
