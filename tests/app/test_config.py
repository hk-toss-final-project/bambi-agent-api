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
    monkeypatch.setenv(
        "AGENT_INTERNAL_TOKEN", "test-agent-internal-token-0123456789abcdef"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    monkeypatch.setenv("WIKI_LLM_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("REPORT_LLM_MODEL", "gpt-4.1-nano")
    monkeypatch.setenv("WIKI_EMBEDDING_MODEL", "text-embedding-3-small")
    monkeypatch.setenv("PERSONAL_WIKI_WORKER_BATCH_SIZE", "3")
    monkeypatch.setenv("PERSONAL_WIKI_JOB_LEASE_SECONDS", "900")
    monkeypatch.setenv("WIKI_BUILD_QUIET_MINUTES", "15")
    monkeypatch.setenv("WIKI_BUILD_MAX_WAIT_MINUTES", "45")

    settings = load_settings()

    assert settings.app_name == "Environment Agent API"
    assert settings.app_version == "2.0.0"
    assert settings.environment == "production"
    assert settings.api_prefix == "/agent/internal/v1"
    assert settings.docs_enabled is False
    assert settings.internal_api_token is not None
    assert (
        settings.internal_api_token.get_secret_value()
        == "test-agent-internal-token-0123456789abcdef"
    )
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "test-secret"
    assert settings.wiki_llm_model == "gpt-4.1-mini"
    assert settings.report_llm_model == "gpt-4.1-nano"
    assert settings.wiki_embedding_model == "text-embedding-3-small"
    assert settings.personal_wiki_worker_batch_size == 3
    assert settings.personal_wiki_job_lease_seconds == 900
    assert settings.wiki_build_quiet_minutes == 15
    assert settings.wiki_build_max_wait_minutes == 45


def test_create_container_uses_postgres_for_publish_snapshots() -> None:
    """DB URL이 있으면 Publish Snapshot 저장소를 PostgreSQL로 구성하는지 검증한다."""
    settings = Settings(
        agent_database_url="postgresql://agent:password@localhost:5432/agent"
    )

    container = create_container(settings)

    assert isinstance(container.database, PostgresPublishSnapshotRepository)
    assert container.mvp_service is not None
