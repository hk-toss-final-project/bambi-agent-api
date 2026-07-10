"""Agent DB Migration, Docker와 설계 문서의 정적 계약을 검증한다."""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]
MIGRATION_PATH = PROJECT_ROOT / "database" / "migrations" / "0001_initial.sql"
SCHEMA_CHECK_PATH = PROJECT_ROOT / "database" / "checks" / "0001_schema_contract.sql"
RLS_CHECK_PATH = PROJECT_ROOT / "database" / "checks" / "0002_rls_contract.sql"
DESIGN_PATH = PROJECT_ROOT / "docs" / "agent-db-design.md"
COMPOSE_PATH = PROJECT_ROOT / "compose.yaml"


def _read(path: Path) -> str:
    """UTF-8 텍스트 파일 내용을 반환한다."""
    return path.read_text(encoding="utf-8")


def test_migration_contains_all_agent_db_feature_tables() -> None:
    """DB-001부터 DB-030까지 담당할 핵심 Table이 Migration에 존재하는지 검증한다."""
    migration = _read(MIGRATION_PATH)
    table_names = set(re.findall(r"CREATE TABLE agent\.([a-z_]+)", migration))
    required_tables = {
        "user_context_snapshots",
        "wiki_source_events",
        "wiki_documents",
        "wiki_document_versions",
        "wiki_chunks",
        "wiki_embeddings",
        "wiki_versions",
        "user_interest_profiles",
        "user_interests",
        "global_sources",
        "global_collection_runs",
        "global_trends",
        "discovery_candidates",
        "generation_requests",
        "generated_content_candidates",
        "citations",
        "content_assets",
        "quality_evaluations",
        "safety_evaluations",
        "recommendation_candidates",
        "prompt_templates",
        "model_configs",
        "retrieval_configs",
        "embedding_configs",
        "agent_jobs",
        "event_outbox",
        "api_keys",
        "usage_logs",
        "audit_logs",
        "publish_snapshots",
    }

    assert required_tables <= table_names


def test_migration_defines_vector_search_and_rls_boundaries() -> None:
    """Vector·Hybrid Index와 개인 데이터 RLS 경계가 선언되는지 검증한다."""
    migration = _read(MIGRATION_PATH)

    assert "CREATE EXTENSION IF NOT EXISTS vector" in migration
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in migration
    assert "embedding vector(1536) NOT NULL" in migration
    assert "USING hnsw (embedding vector_cosine_ops)" in migration
    assert "USING gin (search_vector)" in migration
    assert "content gin_trgm_ops" in migration
    assert "ALTER TABLE agent.wiki_documents ENABLE ROW LEVEL SECURITY" in migration
    assert "CREATE POLICY wiki_document_read" in migration
    assert "CREATE POLICY wiki_document_write" in migration
    assert "namespace_key = 'user/' || agent.current_user_id()" in migration


def test_migration_does_not_create_service_owned_tables() -> None:
    """Agent DB가 Service 계층 소유 Table을 생성하지 않는지 검증한다."""
    migration = _read(MIGRATION_PATH)
    service_owned_tables = {"users", "bookmarks", "cards", "feed_items", "likes"}
    created_tables = set(re.findall(r"CREATE TABLE agent\.([a-z_]+)", migration))

    assert created_tables.isdisjoint(service_owned_tables)


def test_design_maps_every_agent_db_feature_id() -> None:
    """설계 문서가 전체 Agent DB 기능 ID를 빠짐없이 Table에 매핑하는지 검증한다."""
    design = _read(DESIGN_PATH)
    expected_ids = {f"DB-{number:03d}" for number in range(1, 31)}
    documented_ids = set(re.findall(r"DB-\d{3}", design))

    assert expected_ids <= documented_ids


def test_compose_requires_secret_and_initializes_schema() -> None:
    """로컬 Compose가 비밀번호를 요구하고 Migration과 Health Check를 연결하는지 검증한다."""
    compose = _read(COMPOSE_PATH)

    assert "pgvector/pgvector:0.8.1-pg17-bookworm" in compose
    assert "AGENT_DB_PASSWORD:?" in compose
    assert "127.0.0.1:${AGENT_DB_PORT:-5432}:5432" in compose
    assert "/docker-entrypoint-initdb.d/0001_initial.sql:ro" in compose
    assert "pg_isready" in compose


def test_database_schema_contract_is_available() -> None:
    """실제 PostgreSQL에서 실행할 Schema 계약 검사가 제공되는지 검증한다."""
    schema_check = _read(SCHEMA_CHECK_PATH)

    assert "vector extension is missing" in schema_check
    assert "HNSW embedding index is missing" in schema_check
    assert "agent-db schema contract passed" in schema_check


def test_database_rls_contract_is_available() -> None:
    """Runtime Role의 사용자 및 시스템 Scope를 검증하는 SQL이 제공되는지 확인한다."""
    rls_check = _read(RLS_CHECK_PATH)

    assert "CREATE ROLE agent_rls_contract_role NOLOGIN" in rls_check
    assert "user scope expected 1 row" in rls_check
    assert "user scope expected global and own Wiki rows" in rls_check
    assert "user scope deleted % global Wiki rows" in rls_check
    assert "system scope expected 2 rows" in rls_check
    assert "ROLLBACK" in rls_check
