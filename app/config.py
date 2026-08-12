"""Agent API 환경 설정 스키마와 환경변수 로딩 기능."""

import os
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr


class Settings(BaseModel):
    """애플리케이션과 외부 연결에 필요한 환경 설정."""

    model_config = ConfigDict(frozen=True)

    app_name: str = Field(default="Report Builder Agent API", description="애플리케이션 이름")
    app_version: str = Field(default="0.1.0", description="애플리케이션 버전")
    environment: str = Field(default="local", description="실행 환경 이름")
    api_prefix: str = Field(default="/internal/v1", description="내부 API 경로 Prefix")
    docs_enabled: bool = Field(default=True, description="OpenAPI 문서 활성화 여부")
    log_level: str = Field(default="INFO", description="root 로거 레벨 이름")
    log_directory: str = Field(
        default="logs",
        description="회전 파일 로그 디렉터리. 빈 값이면 파일 로그를 끈다(콘솔만).",
    )
    enable_assistant_ui: bool = Field(
        default=True,
        description="키워드 비서 웹 UI(/assistant/**)를 같은 프로세스에 등록할지 여부",
    )
    enable_dev_graph_views: bool = Field(
        default=True,
        description="읽기 전용 에이전트 그래프 화면(/dev/graphs) 활성화 여부",
    )
    enable_dev_agent_api: bool = Field(
        default=False,
        description="개발용 Agent 동기 실행 API 활성화 여부",
    )
    internal_api_token: SecretStr | None = Field(
        default=None,
        min_length=32,
        description="Service API와 Service Worker가 내부 API 호출에 사용하는 Bearer 토큰",
    )
    mcp_server_port: int = Field(
        default=8100,
        ge=1,
        le=65535,
        description="MCP 전용 프로세스가 수신할 내부 포트",
    )
    mcp_server_url: str = Field(
        default="http://localhost:8100/mcp",
        description="외부 MCP Client가 등록할 공개 Streamable HTTP URL",
    )
    mcp_auth_issuer_url: str = Field(
        default="http://localhost:8080",
        description="MCP 보호 리소스 Metadata에 표시할 인증 발급자 URL",
    )
    service_api_base_url: str = Field(
        default="http://localhost:8080",
        description="OAuth access token을 검증할 Service API 내부 주소",
    )
    mcp_oauth_introspection_path: str = Field(
        default="/internal/oauth/introspect",
        description="Service API OAuth token introspection 내부 경로",
    )
    mcp_oauth_timeout_seconds: float = Field(
        default=3.0,
        gt=0,
        le=30,
        description="OAuth token introspection 제한 시간(초)",
    )
    dev_agent_timeout_seconds: int = Field(
        default=180,
        ge=10,
        le=900,
        description="개발용 Agent 동기 실행 제한 시간(초)",
    )
    agent_database_url: str | None = Field(
        default=None, description="Agent DB 연결 문자열"
    )
    vector_store_url: str | None = Field(
        default=None, description="Vector 저장소 연결 문자열"
    )
    openai_api_key: SecretStr | None = Field(
        default=None, description="OpenAI Secret 참조 값"
    )
    tavily_api_key: SecretStr | None = Field(
        default=None, description="Tavily Secret 참조 값"
    )
    naver_client_id: str | None = Field(default=None, description="Naver API Client ID")
    naver_client_secret: SecretStr | None = Field(
        default=None, description="Naver API Client Secret"
    )
    news_api_key: SecretStr | None = Field(
        default=None, description="NewsAPI Secret 참조 값"
    )
    gdelt_base_url: str | None = Field(default=None, description="GDELT API 기본 URL")
    wiki_llm_model: str = Field(
        default="gpt-4.1-mini", description="Personal Wiki 분류 모델"
    )
    report_llm_model: str = Field(
        default="gpt-4.1-mini", description="Report Builder 콘텐츠 생성 모델"
    )
    wiki_read_pipeline_version: Literal["legacy_v1", "langgraph_v2"] = Field(
        default="langgraph_v2",
        description="새 Report Job에 고정할 Wiki 읽기 루프 버전",
    )
    wiki_maintenance_pipeline_version: Literal[
        "legacy_v1", "langgraph_v2", "langgraph_v3"
    ] = Field(
        default="langgraph_v2",
        description="새 Wiki 유지보수 Job에 고정할 실행 루프 버전",
    )
    wiki_embedding_model: str = Field(
        default="text-embedding-3-small",
        description="Personal Wiki Chunk Embedding 모델",
    )
    wiki_embedding_batch_threshold: int = Field(
        default=100,
        ge=0,
        description="이 Chunk 수 이상인 Wiki Embedding을 OpenAI Batch로 전환",
    )
    personal_wiki_worker_batch_size: int = Field(
        default=10, ge=1, le=100, description="Personal Wiki Worker Job Claim 개수"
    )
    personal_wiki_job_concurrency: int = Field(
        default=4,
        ge=1,
        le=50,
        description="Personal Wiki Worker의 실제 동시 Job 실행 수",
    )
    url_collection_worker_batch_size: int = Field(
        default=10, ge=1, le=100, description="URL 수집 Worker Job Claim 개수"
    )
    url_collection_job_concurrency: int = Field(
        default=4,
        ge=1,
        le=20,
        description="URL 수집 Worker의 실제 동시 Job 실행 수",
    )
    report_worker_batch_size: int = Field(
        default=1,
        ge=1,
        le=100,
        description="Report Builder Worker가 한 실행에서 처리할 최대 Job 수",
    )
    report_job_concurrency: int = Field(
        default=1,
        ge=1,
        le=50,
        description="Report Builder Worker의 실제 동시 Job 실행 수",
    )
    briefing_worker_batch_size: int = Field(
        default=1,
        ge=1,
        le=100,
        description="브리핑 준비 Worker가 한 실행에서 처리할 최대 Job 수",
    )
    briefing_job_concurrency: int = Field(
        default=1,
        ge=1,
        le=50,
        description="브리핑 준비 Worker의 실제 동시 Job 실행 수",
    )
    openai_default_rpm: int = Field(
        default=60,
        ge=1,
        description="응답 헤더 관찰 전 OpenAI 요청 상한 기본값",
    )
    openai_default_tpm: int = Field(
        default=60_000,
        ge=1,
        description="응답 헤더 관찰 전 OpenAI Token 상한 기본값",
    )
    wiki_openai_requests_per_job: int = Field(
        default=8,
        ge=1,
        description="Wiki Job 하나의 보수적 OpenAI 요청 예약량",
    )
    wiki_openai_tokens_per_job: int = Field(
        default=30_000,
        ge=0,
        description="Wiki Job 하나의 보수적 OpenAI Token 예약량",
    )
    report_openai_requests_per_job: int = Field(
        default=12,
        ge=1,
        description="Report Job 하나의 보수적 OpenAI 요청 예약량",
    )
    report_openai_tokens_per_job: int = Field(
        default=50_000,
        ge=0,
        description="Report Job 하나의 보수적 OpenAI Token 예약량",
    )
    briefing_openai_requests_per_job: int = Field(
        default=8,
        ge=1,
        description="브리핑 준비 Job 하나의 보수적 OpenAI 요청 예약량",
    )
    briefing_openai_tokens_per_job: int = Field(
        default=30_000,
        ge=0,
        description="브리핑 준비 Job 하나의 보수적 OpenAI Token 예약량",
    )
    openai_batch_max_items: int = Field(
        default=500,
        ge=1,
        le=50_000,
        description="OpenAI Batch 입력 파일 하나의 최대 Item 수",
    )
    openai_batch_max_submissions: int = Field(
        default=1,
        ge=0,
        le=100,
        description="Batch Worker Cycle 하나의 최대 신규 제출 수",
    )
    openai_batch_poll_limit: int = Field(
        default=10,
        ge=1,
        le=1000,
        description="Batch Worker Cycle 하나의 최대 상태 조회 수",
    )
    openai_batch_poll_interval_seconds: int = Field(
        default=60,
        ge=1,
        description="OpenAI Batch 상태 재조회 간격(초)",
    )
    openai_batch_poll_lease_seconds: int = Field(
        default=120,
        ge=1,
        description="분산 Batch Worker 상태 조회 Lease(초)",
    )
    personal_wiki_job_lease_seconds: int = Field(
        default=600, ge=30, le=3600, description="Personal Wiki Job Lease 초"
    )
    wiki_build_quiet_minutes: int = Field(
        default=0,
        ge=0,
        le=1440,
        description=(
            "마지막 원본 수집 후 Wiki Build를 미루는 조용한 시간(분). "
            "0이면 저장 즉시 반영(데모 기본값), 운영에서 저장이 몰릴 때는 "
            "10 등으로 늘려 여러 건을 한 Build로 묶는다"
        ),
    )
    wiki_build_max_wait_minutes: int = Field(
        default=30,
        ge=1,
        le=1440,
        description="첫 대기 원본 발생 후 Wiki Build 최대 대기시간(분)",
    )
    collection_scheduler_tick_seconds: int = Field(
        default=60,
        ge=10,
        le=3600,
        description="Scheduler가 수집 주기 도달 여부를 다시 확인하는 간격(초)",
    )
    enable_collection_scheduler: bool = Field(
        default=True,
        description=(
            "서버 기동 시 수집 Scheduler를 함께 띄울지 여부. "
            "API를 여러 인스턴스로 띄우면 수집이 중복되므로 그때는 끈다"
        ),
    )
    collection_content_fetch_limit: int = Field(
        default=20,
        ge=0,
        le=100,
        description=(
            "Scheduler tick마다 Jina Reader로 본문을 채울 문서 수 (0이면 끔). "
            "수집은 URL만 저장하므로 이 값이 0이면 본문 없는 문서만 쌓인다. "
            "동시 내려받기 수는 GLOBAL_CONTENT_FETCH_CONCURRENCY가 따로 정한다"
        ),
    )
    interest_recalculation_limit: int = Field(
        default=20,
        ge=0,
        le=200,
        description=(
            "Scheduler tick마다 관심사를 다시 계산할 사용자 수 (0이면 끔). "
            "관심사 점수는 계산 시각 기준으로 감쇠하므로 이 값이 0이면 저장이 "
            "멈춘 사용자의 점수가 마지막 Build 시점에 고정된다"
        ),
    )
    interest_recalculation_stale_hours: float = Field(
        default=24.0,
        ge=0.0,
        le=720.0,
        description=(
            "관심사 Profile을 다시 계산하기까지 기다리는 시간(시간). "
            "이 시간이 지난 Profile만 재계산 대상이 된다"
        ),
    )
    maintenance_rebuild_limit: int = Field(
        default=5,
        ge=0,
        le=100,
        description=(
            "Scheduler tick마다 등록할 정기 Wiki 재구성 Job 수 (0이면 끔). "
            "증분 Build는 원본이 들어올 때만 돌아 누적된 중복·고아 문서를 "
            "정리할 기회가 없다. 실제 재구성은 상주 Worker가 수행한다"
        ),
    )
    maintenance_rebuild_stale_hours: float = Field(
        default=168.0,
        ge=1.0,
        le=8760.0,
        description=(
            "사용자별 정기 Wiki 재구성 간격(시간, 기본 7일). 재구성은 LLM 재분류 "
            "비용이 크므로 관심사 재계산보다 훨씬 드물게 돈다"
        ),
    )
    stalled_job_reap_limit: int = Field(
        default=20,
        ge=0,
        le=100,
        description=(
            "Scheduler tick마다 강제 회수할, 시도를 다 쓴 채 Lease가 만료된 "
            "running Job 수 (0이면 끔). claim_runnable_agent_jobs는 이런 Job을 "
            "다시 집지 못해 화면에 '생성 중'이 영구히 멈춰 보이는 문제(JOB-009)를 막는다"
        ),
    )

    @property
    def dev_agent_api_enabled(self) -> bool:
        """개발·테스트 환경에서 명시적으로 허용된 경우에만 개발 API를 활성화한다."""
        return self.enable_dev_agent_api and self.environment in {"local", "test"}


def _optional_env(name: str) -> str | None:
    """빈 문자열을 제외한 선택 환경변수 값을 반환한다."""
    value = os.getenv(name)
    return value if value else None


def _boolean_env(name: str, default: bool) -> bool:
    """환경변수의 일반적인 참·거짓 문자열을 bool로 변환한다."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _integer_env(name: str, default: int) -> int:
    """환경변수의 정수 문자열을 설정 값으로 변환한다."""
    value = os.getenv(name)
    return int(value) if value is not None else default


def _float_env(name: str, default: float) -> float:
    """환경변수의 실수 문자열을 설정 값으로 변환한다."""
    value = os.getenv(name)
    return float(value) if value is not None else default


def load_settings() -> Settings:
    """[SYS-003] 환경변수와 Secret 참조로부터 설정을 로딩한다."""
    load_dotenv()
    return Settings(
        app_name=os.getenv("APP_NAME", "Report Builder Agent API"),
        app_version=os.getenv("APP_VERSION", "0.1.0"),
        environment=os.getenv("APP_ENV", "local"),
        api_prefix=os.getenv("API_PREFIX", "/internal/v1"),
        docs_enabled=_boolean_env("DOCS_ENABLED", True),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        log_directory=os.getenv("LOG_DIR", "logs"),
        enable_assistant_ui=_boolean_env("ENABLE_ASSISTANT_UI", True),
        enable_dev_graph_views=_boolean_env("ENABLE_DEV_GRAPH_VIEWS", True),
        enable_dev_agent_api=_boolean_env("ENABLE_DEV_AGENT_API", False),
        internal_api_token=_optional_env("AGENT_INTERNAL_TOKEN"),
        mcp_server_port=_integer_env("MCP_SERVER_PORT", 8100),
        mcp_server_url=os.getenv("MCP_SERVER_URL", "http://localhost:8100/mcp"),
        mcp_auth_issuer_url=os.getenv(
            "MCP_AUTH_ISSUER_URL",
            "http://localhost:8080",
        ),
        service_api_base_url=os.getenv("SERVICE_API_BASE_URL", "http://localhost:8080"),
        mcp_oauth_introspection_path=os.getenv(
            "MCP_OAUTH_INTROSPECTION_PATH", "/internal/oauth/introspect"
        ),
        mcp_oauth_timeout_seconds=float(
            os.getenv("MCP_OAUTH_TIMEOUT_SECONDS", "3.0")
        ),
        dev_agent_timeout_seconds=_integer_env("DEV_AGENT_TIMEOUT_SECONDS", 180),
        agent_database_url=_optional_env("AGENT_DATABASE_URL"),
        vector_store_url=_optional_env("VECTOR_STORE_URL"),
        openai_api_key=_optional_env("OPENAI_API_KEY"),
        tavily_api_key=_optional_env("TAVILY_API_KEY"),
        naver_client_id=_optional_env("NAVER_CLIENT_ID"),
        naver_client_secret=_optional_env("NAVER_CLIENT_SECRET"),
        news_api_key=_optional_env("NEWS_API_KEY"),
        gdelt_base_url=_optional_env("GDELT_BASE_URL"),
        wiki_llm_model=os.getenv("WIKI_LLM_MODEL", "gpt-4.1-mini"),
        report_llm_model=os.getenv("REPORT_LLM_MODEL", "gpt-4.1-mini"),
        wiki_read_pipeline_version=os.getenv(
            "WIKI_READ_PIPELINE_VERSION", "langgraph_v2"
        ),
        wiki_maintenance_pipeline_version=os.getenv(
            "WIKI_MAINTENANCE_PIPELINE_VERSION", "langgraph_v2"
        ),
        wiki_embedding_model=os.getenv(
            "WIKI_EMBEDDING_MODEL", "text-embedding-3-small"
        ),
        wiki_embedding_batch_threshold=_integer_env(
            "WIKI_EMBEDDING_BATCH_THRESHOLD", 100
        ),
        personal_wiki_worker_batch_size=_integer_env(
            "PERSONAL_WIKI_WORKER_BATCH_SIZE", 10
        ),
        personal_wiki_job_concurrency=_integer_env(
            "PERSONAL_WIKI_JOB_CONCURRENCY", 4
        ),
        url_collection_worker_batch_size=_integer_env(
            "URL_COLLECTION_WORKER_BATCH_SIZE", 10
        ),
        url_collection_job_concurrency=_integer_env(
            "URL_COLLECTION_JOB_CONCURRENCY", 4
        ),
        report_worker_batch_size=_integer_env(
            "REPORT_WORKER_BATCH_SIZE",
            _integer_env("PERSONAL_WIKI_WORKER_BATCH_SIZE", 1),
        ),
        report_job_concurrency=_integer_env("REPORT_JOB_CONCURRENCY", 1),
        briefing_worker_batch_size=_integer_env(
            "BRIEFING_WORKER_BATCH_SIZE",
            _integer_env(
                "REPORT_WORKER_BATCH_SIZE",
                _integer_env("PERSONAL_WIKI_WORKER_BATCH_SIZE", 1),
            ),
        ),
        briefing_job_concurrency=_integer_env(
            "BRIEFING_JOB_CONCURRENCY",
            _integer_env("REPORT_JOB_CONCURRENCY", 1),
        ),
        openai_default_rpm=_integer_env("OPENAI_DEFAULT_RPM", 60),
        openai_default_tpm=_integer_env("OPENAI_DEFAULT_TPM", 60_000),
        wiki_openai_requests_per_job=_integer_env(
            "WIKI_OPENAI_REQUESTS_PER_JOB", 8
        ),
        wiki_openai_tokens_per_job=_integer_env(
            "WIKI_OPENAI_TOKENS_PER_JOB", 30_000
        ),
        report_openai_requests_per_job=_integer_env(
            "REPORT_OPENAI_REQUESTS_PER_JOB", 12
        ),
        report_openai_tokens_per_job=_integer_env(
            "REPORT_OPENAI_TOKENS_PER_JOB", 50_000
        ),
        briefing_openai_requests_per_job=_integer_env(
            "BRIEFING_OPENAI_REQUESTS_PER_JOB", 8
        ),
        briefing_openai_tokens_per_job=_integer_env(
            "BRIEFING_OPENAI_TOKENS_PER_JOB", 30_000
        ),
        openai_batch_max_items=_integer_env("OPENAI_BATCH_MAX_ITEMS", 500),
        openai_batch_max_submissions=_integer_env(
            "OPENAI_BATCH_MAX_SUBMISSIONS", 1
        ),
        openai_batch_poll_limit=_integer_env("OPENAI_BATCH_POLL_LIMIT", 10),
        openai_batch_poll_interval_seconds=_integer_env(
            "OPENAI_BATCH_POLL_INTERVAL_SECONDS", 60
        ),
        openai_batch_poll_lease_seconds=_integer_env(
            "OPENAI_BATCH_POLL_LEASE_SECONDS", 120
        ),
        personal_wiki_job_lease_seconds=_integer_env(
            "PERSONAL_WIKI_JOB_LEASE_SECONDS", 600
        ),
        wiki_build_quiet_minutes=_integer_env("WIKI_BUILD_QUIET_MINUTES", 0),
        wiki_build_max_wait_minutes=_integer_env("WIKI_BUILD_MAX_WAIT_MINUTES", 30),
        collection_scheduler_tick_seconds=_integer_env(
            "COLLECTION_SCHEDULER_TICK_SECONDS", 60
        ),
        enable_collection_scheduler=_boolean_env(
            "ENABLE_COLLECTION_SCHEDULER", True
        ),
        collection_content_fetch_limit=_integer_env(
            "COLLECTION_CONTENT_FETCH_LIMIT", 5
        ),
        interest_recalculation_limit=_integer_env(
            "INTEREST_RECALCULATION_LIMIT", 20
        ),
        interest_recalculation_stale_hours=_float_env(
            "INTEREST_RECALCULATION_STALE_HOURS", 24.0
        ),
        maintenance_rebuild_limit=_integer_env("MAINTENANCE_REBUILD_LIMIT", 5),
        maintenance_rebuild_stale_hours=_float_env(
            "MAINTENANCE_REBUILD_STALE_HOURS", 168.0
        ),
        stalled_job_reap_limit=_integer_env("STALLED_JOB_REAP_LIMIT", 20),
    )
