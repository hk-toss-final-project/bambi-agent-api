"""환경변수 기반 Agent API 설정 로딩을 검증한다."""

from pytest import MonkeyPatch

from app.config import Settings, load_settings
from app.dependencies import create_container
from infrastructure.persistence.postgres_publish_snapshots import (
    PostgresPublishSnapshotRepository,
)


def test_load_settings_reads_environment(monkeypatch: MonkeyPatch) -> None:
    """환경변수와 Secret이 Settings 타입으로 변환되는지 검증한다."""
    monkeypatch.setenv("APP_NAME", "Environment Agent API")
    monkeypatch.setenv("APP_VERSION", "2.0.0")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_PREFIX", "/agent/internal/v1")
    monkeypatch.setenv("DOCS_ENABLED", "false")
    monkeypatch.setenv("ENABLE_DEV_GRAPH_VIEWS", "false")
    monkeypatch.setenv(
        "AGENT_INTERNAL_TOKEN", "test-agent-internal-token-0123456789abcdef"
    )
    monkeypatch.setenv("MCP_SERVER_PORT", "8101")
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    monkeypatch.setenv("WIKI_LLM_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("REPORT_LLM_MODEL", "gpt-4.1-nano")
    monkeypatch.setenv("WIKI_READ_PIPELINE_VERSION", "langgraph_v2")
    monkeypatch.setenv("WIKI_MAINTENANCE_PIPELINE_VERSION", "langgraph_v2")
    monkeypatch.setenv("WIKI_EMBEDDING_MODEL", "text-embedding-3-small")
    monkeypatch.setenv("WIKI_EMBEDDING_BATCH_THRESHOLD", "80")
    monkeypatch.setenv("PERSONAL_WIKI_WORKER_BATCH_SIZE", "3")
    monkeypatch.setenv("PERSONAL_WIKI_JOB_CONCURRENCY", "2")
    monkeypatch.setenv("URL_COLLECTION_WORKER_BATCH_SIZE", "6")
    monkeypatch.setenv("URL_COLLECTION_JOB_CONCURRENCY", "3")
    monkeypatch.setenv("REPORT_WORKER_BATCH_SIZE", "7")
    monkeypatch.setenv("REPORT_JOB_CONCURRENCY", "4")
    monkeypatch.setenv("BRIEFING_WORKER_BATCH_SIZE", "11")
    monkeypatch.setenv("BRIEFING_JOB_CONCURRENCY", "3")
    monkeypatch.setenv("OPENAI_DEFAULT_RPM", "120")
    monkeypatch.setenv("OPENAI_DEFAULT_TPM", "90000")
    monkeypatch.setenv("WIKI_OPENAI_REQUESTS_PER_JOB", "6")
    monkeypatch.setenv("WIKI_OPENAI_TOKENS_PER_JOB", "24000")
    monkeypatch.setenv("REPORT_OPENAI_REQUESTS_PER_JOB", "10")
    monkeypatch.setenv("REPORT_OPENAI_TOKENS_PER_JOB", "45000")
    monkeypatch.setenv("BRIEFING_OPENAI_REQUESTS_PER_JOB", "7")
    monkeypatch.setenv("BRIEFING_OPENAI_TOKENS_PER_JOB", "28000")
    monkeypatch.setenv("OPENAI_BATCH_MAX_ITEMS", "400")
    monkeypatch.setenv("OPENAI_BATCH_MAX_SUBMISSIONS", "2")
    monkeypatch.setenv("OPENAI_BATCH_POLL_LIMIT", "20")
    monkeypatch.setenv("OPENAI_BATCH_POLL_INTERVAL_SECONDS", "45")
    monkeypatch.setenv("OPENAI_BATCH_POLL_LEASE_SECONDS", "90")
    monkeypatch.setenv("PERSONAL_WIKI_JOB_LEASE_SECONDS", "900")
    monkeypatch.setenv("WIKI_BUILD_QUIET_MINUTES", "15")
    monkeypatch.setenv("WIKI_BUILD_MAX_WAIT_MINUTES", "45")

    settings = load_settings()

    assert settings.app_name == "Environment Agent API"
    assert settings.app_version == "2.0.0"
    assert settings.environment == "production"
    assert settings.api_prefix == "/agent/internal/v1"
    assert settings.docs_enabled is False
    assert settings.enable_dev_graph_views is False
    assert settings.internal_api_token is not None
    assert (
        settings.internal_api_token.get_secret_value()
        == "test-agent-internal-token-0123456789abcdef"
    )
    assert settings.mcp_server_port == 8101
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "test-secret"
    assert settings.wiki_llm_model == "gpt-4.1-mini"
    assert settings.report_llm_model == "gpt-4.1-nano"
    assert settings.wiki_read_pipeline_version == "langgraph_v2"
    assert settings.wiki_maintenance_pipeline_version == "langgraph_v2"
    assert settings.wiki_embedding_model == "text-embedding-3-small"
    assert settings.wiki_embedding_batch_threshold == 80
    assert settings.personal_wiki_worker_batch_size == 3
    assert settings.personal_wiki_job_concurrency == 2
    assert settings.url_collection_worker_batch_size == 6
    assert settings.url_collection_job_concurrency == 3
    assert settings.report_job_concurrency == 4
    assert settings.briefing_worker_batch_size == 11
    assert settings.briefing_job_concurrency == 3
    assert settings.openai_default_rpm == 120
    assert settings.openai_default_tpm == 90_000
    assert settings.wiki_openai_requests_per_job == 6
    assert settings.wiki_openai_tokens_per_job == 24_000
    assert settings.report_openai_requests_per_job == 10
    assert settings.report_openai_tokens_per_job == 45_000
    assert settings.briefing_openai_requests_per_job == 7
    assert settings.briefing_openai_tokens_per_job == 28_000
    assert settings.openai_batch_max_items == 400
    assert settings.openai_batch_max_submissions == 2
    assert settings.openai_batch_poll_limit == 20
    assert settings.openai_batch_poll_interval_seconds == 45
    assert settings.openai_batch_poll_lease_seconds == 90
    assert settings.report_worker_batch_size == 7
    assert settings.personal_wiki_job_lease_seconds == 900
    assert settings.wiki_build_quiet_minutes == 15
    assert settings.wiki_build_max_wait_minutes == 45


def test_settings_uses_dedicated_mcp_port_by_default() -> None:
    """MCP 전용 프로세스는 Agent API와 다른 8100 포트를 기본으로 사용한다."""
    settings = Settings()

    assert settings.mcp_server_port == 8100
    assert settings.mcp_server_url == "http://localhost:8100/mcp"


def test_settings_uses_workload_specific_llm_models_by_default() -> None:
    """Wiki 빌드와 리포트 생성이 작업별 기본 모델을 사용하는지 검증한다."""
    settings = Settings()

    assert settings.wiki_llm_model == "gpt-4.1-mini"
    assert settings.report_llm_model == "gpt-4o-mini"


def test_wiki_pipeline_versions_default_to_langgraph_v2() -> None:
    """새 Job은 Wiki 읽기·유지 LangGraph V2를 기본 실행 경로로 사용한다."""
    settings = Settings()

    assert settings.wiki_read_pipeline_version == "langgraph_v2"
    assert settings.wiki_maintenance_pipeline_version == "langgraph_v2"


def test_wiki_maintenance_pipeline_accepts_langgraph_v3_canary() -> None:
    """유지 V3를 명시하면 허용하되 읽기·유지 기본값은 바꾸지 않는다."""
    settings = Settings(wiki_maintenance_pipeline_version="langgraph_v3")

    assert settings.wiki_read_pipeline_version == "langgraph_v2"
    assert settings.wiki_maintenance_pipeline_version == "langgraph_v3"


def test_interactive_worker_defaults_prioritize_short_queue_delay() -> None:
    """환경변수가 없어도 Wiki·URL Worker가 짧은 대기와 병렬 처리를 기본으로 쓴다."""
    settings = Settings()

    assert settings.personal_wiki_worker_batch_size == 10
    assert settings.personal_wiki_job_concurrency == 4
    assert settings.url_collection_worker_batch_size == 10
    assert settings.url_collection_job_concurrency == 4
    assert settings.wiki_build_quiet_minutes == 0


def test_report_batch_size_falls_back_to_personal_wiki_batch_size(
    monkeypatch: MonkeyPatch,
) -> None:
    """전용 설정이 없는 기존 배포는 종전 Worker Batch 크기를 유지한다."""
    monkeypatch.setenv("PERSONAL_WIKI_WORKER_BATCH_SIZE", "9")
    monkeypatch.delenv("REPORT_WORKER_BATCH_SIZE", raising=False)

    settings = load_settings()

    assert settings.report_worker_batch_size == 9


def test_briefing_worker_settings_fall_back_to_report_worker_settings(
    monkeypatch: MonkeyPatch,
) -> None:
    """전용 설정이 없는 기존 배포는 종전 Report Worker 처리량을 유지한다."""
    monkeypatch.setenv("REPORT_WORKER_BATCH_SIZE", "9")
    monkeypatch.setenv("REPORT_JOB_CONCURRENCY", "3")
    monkeypatch.delenv("BRIEFING_WORKER_BATCH_SIZE", raising=False)
    monkeypatch.delenv("BRIEFING_JOB_CONCURRENCY", raising=False)

    settings = load_settings()

    assert settings.briefing_worker_batch_size == 9
    assert settings.briefing_job_concurrency == 3


def test_create_container_uses_postgres_for_publish_snapshots() -> None:
    """DB URL이 있으면 Publish Snapshot 저장소를 PostgreSQL로 구성하는지 검증한다."""
    settings = Settings(
        agent_database_url="postgresql://agent:password@localhost:5432/agent"
    )

    container = create_container(settings)

    assert isinstance(container.database, PostgresPublishSnapshotRepository)
    assert container.mvp_service is not None
