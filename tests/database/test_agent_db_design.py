"""Agent DB Migration, Docker와 설계 문서의 정적 계약을 검증한다."""

import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]
PROJECT_README_PATH = PROJECT_ROOT / "README.md"
MIGRATION_PATH = PROJECT_ROOT / "database" / "migrations" / "0001_initial.sql"
BATCH_MIGRATION_PATH = (
    PROJECT_ROOT / "database" / "migrations" / "0002_publish_snapshot_batches.sql"
)
WEB_CLIPPING_MIGRATION_PATH = (
    PROJECT_ROOT / "database" / "migrations" / "0003_web_clipping_markdown.sql"
)
SOURCE_SEPARATION_MIGRATION_PATH = (
    PROJECT_ROOT
    / "database"
    / "migrations"
    / "0004_separate_user_sources_from_llm_wiki.sql"
)
STRUCTURED_WIKI_MIGRATION_PATH = (
    PROJECT_ROOT
    / "database"
    / "migrations"
    / "0005_structure_llm_wiki_documents.sql"
)
REPORT_BUILDER_RENAME_MIGRATION_PATH = (
    PROJECT_ROOT
    / "database"
    / "migrations"
    / "0006_rename_report_builder_contracts.sql"
)
GLOBAL_SOURCE_CACHE_MIGRATION_PATH = (
    PROJECT_ROOT
    / "database"
    / "migrations"
    / "0008_extract_global_source_cache.sql"
)
USER_CONTEXT_SELECTION_MIGRATION_PATH = (
    PROJECT_ROOT
    / "database"
    / "migrations"
    / "0009_user_context_onboarding_selections.sql"
)
MIGRATION_PATHS = (
    MIGRATION_PATH,
    BATCH_MIGRATION_PATH,
    WEB_CLIPPING_MIGRATION_PATH,
    SOURCE_SEPARATION_MIGRATION_PATH,
    STRUCTURED_WIKI_MIGRATION_PATH,
    REPORT_BUILDER_RENAME_MIGRATION_PATH,
    GLOBAL_SOURCE_CACHE_MIGRATION_PATH,
    USER_CONTEXT_SELECTION_MIGRATION_PATH,
)
SCHEMA_CHECK_PATH = PROJECT_ROOT / "database" / "checks" / "0001_schema_contract.sql"
RLS_CHECK_PATH = PROJECT_ROOT / "database" / "checks" / "0002_rls_contract.sql"
DESIGN_PATH = PROJECT_ROOT / "docs" / "agent-db-design.md"
TABLE_CATALOG_PATH = PROJECT_ROOT / "docs" / "agent-db-table-catalog.md"
COLUMN_DICTIONARY_PATH = PROJECT_ROOT / "docs" / "agent-db-column-dictionary.md"
COMPOSE_PATH = PROJECT_ROOT / "compose.yaml"
DATABASE_README_PATH = PROJECT_ROOT / "database" / "README.md"
SEED_PATH = PROJECT_ROOT / "database" / "seeds" / "0001_dev_publish_snapshots.sql"
BATCH_SEED_PATH = (
    PROJECT_ROOT / "database" / "seeds" / "0002_dev_publish_snapshot_batch.sql"
)
CLIPPING_SEED_PATH = (
    PROJECT_ROOT / "database" / "seeds" / "0003_dev_web_clippings.sql"
)
CLIPPING_SEED_GENERATOR_PATH = (
    PROJECT_ROOT / "scripts" / "generate_web_clipping_seed.py"
)
CLIPPING_DUMMY_PATH = PROJECT_ROOT / "dummy" / "clippings"
USER_URL_SEED_PATH = PROJECT_ROOT / "database" / "seeds" / "0004_dev_user_urls.sql"
USER_URL_SEED_GENERATOR_PATH = (
    PROJECT_ROOT / "scripts" / "generate_user_url_seed.py"
)
USER_URL_DUMMY_PATH = PROJECT_ROOT / "dummy" / "urls" / "url.txt"
MIGRATION_RUNNER_PATH = PROJECT_ROOT / "scripts" / "run_agent_db_migrations.sh"
DATABASE_INITIALIZER_PATH = PROJECT_ROOT / "scripts" / "initialize_agent_db.sh"
DATABASE_STARTER_PATH = PROJECT_ROOT / "scripts" / "start_agent_db.sh"
DOCKERFILE_PATH = PROJECT_ROOT / "Dockerfile"


def _read(path: Path) -> str:
    """UTF-8 텍스트 파일 내용을 반환한다."""
    return path.read_text(encoding="utf-8")


def _run_database_starter(
    tmp_path: Path,
    *,
    initializer_exit_code: int = 0,
    unhealthy_inspections: int = 1,
    health_max_attempts: int = 3,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """가짜 Docker 명령으로 Agent DB 시작 스크립트의 호출 순서를 기록한다."""
    call_log_path = tmp_path / "docker-calls.log"
    inspection_count_path = tmp_path / "docker-inspection-count"
    fake_docker_path = tmp_path / "docker"
    fake_docker_path.write_text(
        """#!/bin/sh
printf '%s|%s\\n' "$PWD" "$*" >> "$DOCKER_CALL_LOG"
if [ "$2" = "exec" ]; then
    exit "$DOCKER_INITIALIZER_EXIT_CODE"
fi
if [ "$2" = "ps" ]; then
    printf '%s\\n' 'fake-agent-db-container-id'
    exit 0
fi
if [ "$1" = "inspect" ]; then
    inspection_count=0
    if [ -f "$DOCKER_INSPECTION_COUNT_FILE" ]; then
        inspection_count="$(sed -n '1p' "$DOCKER_INSPECTION_COUNT_FILE")"
    fi
    inspection_count=$((inspection_count + 1))
    printf '%s\\n' "$inspection_count" > "$DOCKER_INSPECTION_COUNT_FILE"
    if [ "$inspection_count" -le "$DOCKER_UNHEALTHY_INSPECTIONS" ]; then
        printf '%s\\n' 'unhealthy'
    else
        printf '%s\\n' 'healthy'
    fi
fi
""",
        encoding="utf-8",
    )
    fake_docker_path.chmod(0o755)

    environment = os.environ.copy()
    environment["PATH"] = f"{tmp_path}:{environment['PATH']}"
    environment["DOCKER_CALL_LOG"] = str(call_log_path)
    environment["DOCKER_INITIALIZER_EXIT_CODE"] = str(initializer_exit_code)
    environment["DOCKER_INSPECTION_COUNT_FILE"] = str(inspection_count_path)
    environment["DOCKER_UNHEALTHY_INSPECTIONS"] = str(unhealthy_inspections)
    environment["AGENT_DB_HEALTH_MAX_ATTEMPTS"] = str(health_max_attempts)
    environment["AGENT_DB_HEALTH_POLL_SECONDS"] = "0"
    result = subprocess.run(
        ["/bin/sh", str(DATABASE_STARTER_PATH)],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    calls = call_log_path.read_text(encoding="utf-8").splitlines()

    return result, calls


def test_migration_contains_all_agent_db_feature_tables() -> None:
    """DB-001부터 DB-030까지 담당할 핵심 Table이 Migration에 존재하는지 검증한다."""
    migration = "\n".join(_read(path) for path in MIGRATION_PATHS)
    table_names = set(re.findall(r"CREATE TABLE agent\.([a-z_]+)", migration))
    required_tables = {
        "user_context_snapshots",
        "wiki_source_events",
        "user_source_documents",
        "user_source_document_versions",
        "wiki_documents",
        "wiki_document_versions",
        "wiki_document_sources",
        "wiki_document_relations",
        "wiki_chunks",
        "wiki_embeddings",
        "wiki_versions",
        "wiki_version_documents",
        "user_interest_profiles",
        "user_interests",
        "global_sources",
        "global_collection_runs",
        "global_source_documents",
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


def test_user_context_migration_adds_onboarding_selection_columns() -> None:
    """DB-001 Snapshot이 온보딩 분류체계 버전과 선택 ID 배열을 보존하는지 검증한다."""
    migration = _read(USER_CONTEXT_SELECTION_MIGRATION_PATH)

    assert "ADD COLUMN interest_taxonomy_version text" in migration
    assert "ADD COLUMN selected_category_ids text[] NOT NULL DEFAULT '{}'" in migration
    assert "ADD COLUMN selected_topic_ids text[] NOT NULL DEFAULT '{}'" in migration
    assert "cardinality(selected_category_ids) <= 8" in migration
    assert "cardinality(selected_topic_ids) <= 12" in migration
    assert "OR interest_taxonomy_version IS NOT NULL" in migration
    assert "VALUES (9," in migration


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


def test_report_builder_rename_migration_updates_existing_generation_jobs() -> None:
    """기존 생성 Job과 기능 ID가 새 Report Builder 실행 계약으로 이전되는지 검증한다."""
    migration = _read(REPORT_BUILDER_RENAME_MIGRATION_PATH)

    assert "job_type = 'report_generation'" in migration
    assert "WHERE job_type = 'bambi_generation'" in migration
    assert "feature_id = 'REPORT-'" in migration
    assert "WHERE feature_id LIKE 'BAMBI-%'" in migration
    assert (
        "VALUES (6, 'Rename legacy generation contracts to Report Builder')"
        in migration
    )


def test_design_maps_every_agent_db_feature_id() -> None:
    """설계 문서가 전체 Agent DB 기능 ID를 빠짐없이 Table에 매핑하는지 검증한다."""
    design = _read(DESIGN_PATH)
    expected_ids = {f"DB-{number:03d}" for number in range(1, 31)}
    documented_ids = set(re.findall(r"DB-\d{3}", design))

    assert expected_ids <= documented_ids


def test_table_catalog_documents_every_migration_table() -> None:
    """테이블 카탈로그가 Migration의 모든 Table을 정확히 한 번씩 문서화하는지 검증한다."""
    migration = "\n".join(_read(path) for path in MIGRATION_PATHS)
    catalog = _read(TABLE_CATALOG_PATH)
    created_tables = set(re.findall(r"CREATE TABLE agent\.([a-z_]+)", migration))
    catalog_rows = re.findall(r"^\| ([a-z][a-z_]*) \|", catalog, re.MULTILINE)

    assert len(catalog_rows) == len(set(catalog_rows))
    assert set(catalog_rows) == created_tables


def test_column_dictionary_documents_every_migration_column() -> None:
    """컬럼 사전이 모든 Migration의 Table과 Column을 정확히 문서화하는지 검증한다."""
    expected: dict[str, set[str]] = {}

    for migration_path in MIGRATION_PATHS:
        migration = _read(migration_path)
        for match in re.finditer(
            r"CREATE TABLE agent\.([a-z_]+) \((.*?)\n\);",
            migration,
            re.DOTALL,
        ):
            table_name, table_body = match.groups()
            expected[table_name] = set(
                re.findall(r"^    ([a-z_]+)\s+[a-z]", table_body, re.MULTILINE)
            )

        for match in re.finditer(
            r"ALTER TABLE agent\.([a-z_]+)(.*?);",
            migration,
            re.DOTALL,
        ):
            table_name, alter_body = match.groups()
            expected.setdefault(table_name, set()).update(
                re.findall(r"ADD COLUMN ([a-z_]+)", alter_body)
            )
            expected[table_name].difference_update(
                re.findall(r"DROP COLUMN ([a-z_]+)", alter_body)
            )

    dictionary = _read(COLUMN_DICTIONARY_PATH)
    sections = list(
        re.finditer(
            r"^### ([a-z_]+)\n(.*?)(?=^### |^## |\Z)",
            dictionary,
            re.MULTILINE | re.DOTALL,
        )
    )
    documented: dict[str, set[str]] = {}

    for match in sections:
        table_name, section_body = match.groups()
        columns = re.findall(r"^\| ([a-z_]+) \|", section_body, re.MULTILINE)
        assert len(columns) == len(set(columns)), f"중복 컬럼 문서: {table_name}"
        documented[table_name] = set(columns)

    assert len(sections) == len(documented)
    assert documented == expected


def test_compose_requires_secret_and_runs_database_initializer() -> None:
    """Compose가 DB 시작마다 Migration과 선택적 개발 Seed를 같은 경로로 실행한다."""
    compose = _read(COMPOSE_PATH)

    # PostgreSQL 17.9 미만은 UTF-8 본문 substring()이 깨진다(BUG #19406).
    assert "pgvector/pgvector:0.8.5-pg17-bookworm" in compose
    assert "AGENT_DB_PASSWORD:?" in compose
    assert "127.0.0.1:${AGENT_DB_PORT:-5432}:5432" in compose
    assert "./database/migrations:/opt/bambi/migrations:ro" in compose
    assert "./database/seeds:/opt/bambi/seeds:ro" in compose
    assert (
        "./scripts/run_agent_db_migrations.sh:"
        "/usr/local/bin/run-agent-db-migrations:ro" in compose
    )
    assert (
        "./scripts/initialize_agent_db.sh:"
        "/usr/local/bin/initialize-agent-db:ro" in compose
    )
    assert "post_start:" in compose
    assert "command: /bin/sh /usr/local/bin/initialize-agent-db" in compose
    assert "/docker-entrypoint-initdb.d/" not in compose
    assert "initialize-agent-db --check" in compose
    assert "pg_isready" in compose


def test_migration_runner_applies_only_pending_versioned_files() -> None:
    """Runner가 파일 순서, 적용 이력과 동시 실행 잠금을 강제하는지 검증한다."""
    runner = _read(MIGRATION_RUNNER_PATH)

    assert "[0-9][0-9][0-9][0-9]_*.sql" in runner
    assert "pg_advisory_lock" in runner
    assert "pg_advisory_unlock" in runner
    assert "agent.schema_migrations" in runner
    assert "max(version)" in runner
    assert "AS should_apply" in runner
    assert r"\\gset" in runner
    assert r"\\ir %s" in runner
    assert "-v ON_ERROR_STOP=1" in runner
    assert 'MODE="${1:-}"' in runner
    assert 'if [ "$MODE" = "--check" ]' in runner
    assert 'DATABASE_URL="${AGENT_DATABASE_URL:-}"' in runner
    assert 'pg_isready -q -d "$DATABASE_URL"' in runner


def test_database_initializer_runs_migrations_before_dev_seeds() -> None:
    """DB 시작 경로가 Schema 후 변경된 개발 Seed만 적용하는지 검증한다."""
    initializer = _read(DATABASE_INITIALIZER_PATH)

    migration_position = initializer.index('/bin/sh "$migration_runner" "$MODE"')
    seed_position = initializer.index('expected_checksum="$(seed_checksum)"')

    assert migration_position < seed_position
    assert "AGENT_DB_APPLY_DEV_SEEDS:-true" in initializer
    assert "run_psql -X -v ON_ERROR_STOP=1" in initializer
    assert "sha256sum" in initializer
    assert "flock -x" in initializer
    assert 'if [ "$MODE" = "--check" ]' in initializer
    assert "AGENT_DB_MIGRATION_RUNNER_PATH" in initializer


def test_database_initializer_tracks_deploy_seed_checksum_in_database() -> None:
    """배포 Initializer가 DB 잠금과 최신 Checksum으로 Seed를 한 번만 적용하는지 검증한다."""
    initializer = _read(DATABASE_INITIALIZER_PATH)

    assert "AGENT_DB_SEED_STATE_BACKEND" in initializer
    assert "pg_advisory_lock" in initializer
    assert "pg_advisory_unlock" in initializer
    assert "agent.audit_logs" in initializer
    assert "agent-db-initializer" in initializer
    assert "development_seed_applied" in initializer
    assert "ORDER BY created_at DESC, id DESC" in initializer
    assert "-v seed_checksum=" in initializer


def test_runtime_image_contains_database_initialization_client() -> None:
    """배포 one-shot 작업 이미지에 psql과 pg_isready가 설치되는지 검증한다."""
    dockerfile = _read(DOCKERFILE_PATH)

    assert "postgresql-client" in dockerfile


def test_database_starter_initializes_before_waiting_for_health(tmp_path: Path) -> None:
    """실행 중인 DB도 초기화한 뒤 최종 Health 상태를 기다리는지 검증한다."""
    result, calls = _run_database_starter(tmp_path)
    project_root = str(PROJECT_ROOT)

    assert result.returncode == 0, result.stderr
    assert calls[:3] == [
        f"{project_root}|compose up -d agent-db",
        (
            f"{project_root}|compose exec -T -u postgres agent-db "
            "/bin/sh /usr/local/bin/initialize-agent-db"
        ),
        f"{project_root}|compose ps -q agent-db",
    ]
    assert len(calls) == 5
    assert all(
        call.startswith(f"{project_root}|inspect --format ") for call in calls[3:]
    )
    assert "Agent DB Health Check 통과" in result.stdout


def test_database_starter_stops_when_initialization_fails(tmp_path: Path) -> None:
    """초기화 실패를 숨기지 않고 Health 대기 전에 종료하는지 검증한다."""
    result, calls = _run_database_starter(tmp_path, initializer_exit_code=23)

    assert result.returncode == 23
    assert len(calls) == 2
    assert calls[-1].endswith(
        "compose exec -T -u postgres agent-db "
        "/bin/sh /usr/local/bin/initialize-agent-db"
    )


def test_database_starter_fails_when_health_does_not_recover(tmp_path: Path) -> None:
    """초기화 후에도 Health 상태가 회복되지 않으면 제한 횟수 뒤 실패하는지 검증한다."""
    result, calls = _run_database_starter(
        tmp_path,
        unhealthy_inspections=3,
        health_max_attempts=3,
    )

    assert result.returncode == 1
    assert sum("|inspect --format " in call for call in calls) == 3
    assert "제한 시간 안에 통과하지 못했습니다: unhealthy" in result.stderr


def test_database_readme_uses_starter_for_repeatable_initialization() -> None:
    """실행 중인 DB에도 적용되는 시작 스크립트를 표준 명령으로 안내하는지 검증한다."""
    readme = _read(DATABASE_README_PATH)

    assert readme.count("./scripts/start_agent_db.sh") >= 2
    assert "이미 실행 중인 컨테이너" in readme
    assert "`post_start`가 다시 실행되지 않으므로" in readme
    assert "AGENT_DB_SEED_STATE_BACKEND=database" in readme
    assert "`agent.audit_logs`" in readme
    assert "API·Worker를 먼저 기동하지 않습니다" in readme


def test_project_readme_uses_database_starter() -> None:
    """프로젝트 실행 안내가 반복 가능한 Agent DB 시작 명령을 사용하는지 검증한다."""
    readme = _read(PROJECT_README_PATH)

    assert "./scripts/start_agent_db.sh" in readme
    assert "이미 실행 중인 DB에도" in readme


def test_dev_seed_builds_service_worker_snapshot_dependency_chain() -> None:
    """개발 Seed가 Snapshot 외래키 원천과 고정 연동 데이터를 순서대로 생성하는지 검증한다."""
    seed = _read(SEED_PATH)
    required_inserts = [
        "INSERT INTO agent.user_context_snapshots",
        "INSERT INTO agent.agent_jobs",
        "INSERT INTO agent.generation_requests",
        "INSERT INTO agent.generation_runs",
        "INSERT INTO agent.generated_content_candidates",
        "INSERT INTO agent.citations",
        "INSERT INTO agent.publish_snapshots",
    ]

    positions = [seed.index(statement) for statement in required_inserts]

    assert positions == sorted(positions)
    assert "mock-user-001" in seed
    assert "mock-content-001" in seed
    assert "ON CONFLICT" in seed
    assert '"citation_id"' in seed


def test_batch_migration_defines_claim_lease_and_retry_contract() -> None:
    """두 번째 Migration이 Batch Claim과 멱등 ACK에 필요한 필드를 추가하는지 검증한다."""
    migration = _read(BATCH_MIGRATION_PATH)

    assert "ADD COLUMN lease_expires_at timestamptz" in migration
    assert "ADD COLUMN claim_id uuid" in migration
    assert "ADD COLUMN claimed_by text" in migration
    assert "ADD COLUMN attempt_count integer" in migration
    assert "ADD COLUMN next_attempt_at timestamptz" in migration
    assert "CHECK (status IN ('ready', 'claimed', 'published'" in migration
    assert "uq_publish_attempts_snapshot_claim" in migration
    assert "ix_publish_snapshots_claimable" in migration
    assert "VALUES (2, 'Publish Snapshot batch claim and lease')" in migration


def test_web_clipping_migration_defines_markdown_frontmatter_contract() -> None:
    """세 번째 Migration이 웹 클리핑 Markdown과 Frontmatter 필드를 추가하는지 검증한다."""
    migration = _read(WEB_CLIPPING_MIGRATION_PATH)

    assert "ALTER TABLE agent.wiki_document_versions" in migration
    assert "ADD COLUMN author text" in migration
    assert "ADD COLUMN published_at timestamptz" in migration
    assert "ADD COLUMN clipped_on date" in migration
    assert "ADD COLUMN description text" in migration
    assert "ADD COLUMN tags text[] NOT NULL DEFAULT '{}'" in migration
    assert "ADD COLUMN content_format text" in migration
    assert "WHEN normalized_content IS NOT NULL THEN 'markdown'" in migration
    assert "ELSE 'external_object'" in migration
    assert "CHECK (content_format IN ('markdown', 'plain_text', 'external_object'))" in migration
    assert "ix_wiki_document_versions_tags" in migration
    assert "ix_wiki_document_versions_clipped" in migration
    assert "VALUES (3, 'Store web clipping Markdown fields')" in migration


def test_source_separation_migration_moves_raw_data_out_of_llm_wiki() -> None:
    """네 번째 Migration이 사용자 원본과 생성된 LLM Wiki의 경계를 분리하는지 검증한다."""
    migration = _read(SOURCE_SEPARATION_MIGRATION_PATH)

    assert "CREATE TABLE agent.user_source_documents" in migration
    assert "CREATE TABLE agent.user_source_document_versions" in migration
    assert "CREATE TABLE agent.wiki_document_sources" in migration
    assert "raw_content text" in migration
    assert "INSERT INTO agent.user_source_documents" in migration
    assert "INSERT INTO agent.user_source_document_versions" in migration
    assert "'source_document_id', job.payload ->> 'document_id'" in migration
    assert "UPDATE agent.wiki_source_events AS event" in migration
    assert "'source_document_version_id', event.payload ->> 'document_version_id'" in migration
    assert "DELETE FROM agent.wiki_documents" in migration
    assert "DROP COLUMN author" in migration
    assert "DROP COLUMN content_format" in migration
    assert "ALTER TABLE agent.user_source_documents ENABLE ROW LEVEL SECURITY" in migration
    assert "VALUES (4, 'Separate user source documents from generated LLM Wiki')" in migration


def test_structured_wiki_migration_models_vault_files_and_snapshots() -> None:
    """다섯 번째 Migration이 Wiki 파일 유형, 관계와 Build 구성을 구조화하는지 검증한다."""
    migration = _read(STRUCTURED_WIKI_MIGRATION_PATH)

    assert "ADD COLUMN document_kind text" in migration
    assert "ADD COLUMN document_key text" in migration
    assert "ADD COLUMN file_path text" in migration
    assert "ADD COLUMN domain text" in migration
    assert "document_kind IN ('document', 'entity', 'concept', 'schema')" in migration
    assert "uq_wiki_documents_logical_key" in migration
    assert "uq_wiki_documents_file_path" in migration
    assert "uq_wiki_documents_schema_per_namespace" in migration
    assert "CREATE TABLE agent.wiki_document_relations" in migration
    assert "CREATE TABLE agent.wiki_version_documents" in migration
    assert "FOREIGN KEY (wiki_version_id, namespace_key)" in migration
    assert "FOREIGN KEY (document_version_id, namespace_key)" in migration
    assert (
        "ALTER TABLE agent.wiki_document_relations ENABLE ROW LEVEL SECURITY"
        in migration
    )
    assert (
        "ALTER TABLE agent.wiki_version_documents ENABLE ROW LEVEL SECURITY"
        in migration
    )
    assert "VALUES (5, 'Structure LLM Wiki documents and snapshots')" in migration


def test_batch_seed_provides_three_resettable_mock_snapshots() -> None:
    """Batch Seed가 세 콘텐츠를 준비하고 반복 적용 시 Claim 상태를 초기화하는지 검증한다."""
    seed = _read(BATCH_SEED_PATH)

    assert "mock-content-002" in seed
    assert "mock-content-003" in seed
    assert "mock-user-002" in seed
    assert "mock-user-003" in seed
    assert "DELETE FROM agent.publish_attempts" in seed
    assert "attempt_count = 0" in seed
    assert "claim_id = NULL" in seed
    assert "status = 'ready'" in seed


def test_web_clipping_seed_is_generated_from_every_dummy_markdown() -> None:
    """생성된 Seed가 dummy/clippings의 모든 Markdown과 동기화됐는지 검증한다."""
    result = subprocess.run(
        [sys.executable, str(CLIPPING_SEED_GENERATOR_PATH), "--check"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    seed = _read(CLIPPING_SEED_PATH)
    clipping_paths = sorted(CLIPPING_DUMMY_PATH.glob("*.md"))

    assert result.returncode == 0, result.stderr
    assert clipping_paths
    for clipping_path in clipping_paths:
        relative_path = clipping_path.relative_to(PROJECT_ROOT).as_posix()
        assert relative_path in seed


def test_web_clipping_seed_builds_resettable_worker_dependency_chain() -> None:
    """클리핑 Seed가 사용자·Job·Event·원본문서·Version을 순서대로 준비하는지 검증한다."""
    seed = _read(CLIPPING_SEED_PATH)
    required_inserts = [
        "INSERT INTO agent.user_context_snapshots",
        "INSERT INTO agent.agent_jobs",
        "INSERT INTO agent.wiki_source_events",
        "INSERT INTO agent.user_source_documents",
        "INSERT INTO agent.user_source_document_versions",
    ]
    positions = [seed.index(statement) for statement in required_inserts]

    assert positions == sorted(positions)
    assert "mock-clipping-user" in seed
    assert "'28'" in seed
    assert "'user/28'" in seed
    assert "personal_wiki_build" in seed
    assert "'queued'" in seed
    assert "'received'" in seed
    assert "'markdown'" in seed
    assert '"source_document_id"' in seed
    assert '"source_document_version_id"' in seed
    assert "INSERT INTO agent.wiki_documents (" not in seed
    assert "INSERT INTO agent.wiki_document_versions (" not in seed
    assert "DELETE FROM agent.agent_job_attempts" in seed
    assert "DELETE FROM agent.wiki_documents AS document" in seed
    assert "ON CONFLICT (id) DO UPDATE" in seed


def test_web_clipping_seed_preserves_existing_user_context_snapshot() -> None:
    """클리핑 Seed가 기존 사용자의 같은 버전 Context Snapshot을 덮어쓰지 않는지 검증한다."""
    seed = _read(CLIPPING_SEED_PATH)
    context_insert_start = seed.index("INSERT INTO agent.user_context_snapshots")
    context_insert_end = seed.index("INSERT INTO agent.agent_jobs")
    context_insert = seed[context_insert_start:context_insert_end]

    assert "ON CONFLICT (user_id, context_version) DO NOTHING" in context_insert
    assert "ON CONFLICT (id) DO UPDATE" not in context_insert


def test_web_clipping_seed_preserves_wiki_documents_referenced_by_citations() -> None:
    """클리핑 Seed가 Citation이 참조하는 Wiki 문서를 삭제 대상에서 제외하는지 검증한다."""
    seed = _read(CLIPPING_SEED_PATH)
    cleanup_start = seed.index("DELETE FROM agent.wiki_documents AS document")
    cleanup_end = seed.index("DELETE FROM agent.user_interest_profiles")
    cleanup = seed[cleanup_start:cleanup_end]

    assert "NOT EXISTS" in cleanup
    assert "JOIN agent.citations AS citation" in cleanup
    assert "citation.document_version_id = version.id" in cleanup
    assert "citation.chunk_id = chunk.id" in cleanup


def test_user_url_seed_is_generated_from_dummy_url_file() -> None:
    """생성된 URL Seed가 dummy/urls의 목록과 동기화됐는지 검증한다."""
    result = subprocess.run(
        [sys.executable, str(USER_URL_SEED_GENERATOR_PATH), "--check"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    seed = _read(USER_URL_SEED_PATH)
    urls = [
        line.strip()
        for line in _read(USER_URL_DUMMY_PATH).splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert result.returncode == 0, result.stderr
    assert urls
    for url in urls:
        assert url in seed


def test_user_url_seed_registers_heads_without_overwriting_collection_results() -> None:
    """URL Seed가 Event·문서 Head만 만들고 기존 수집 상태와 Version을 보존하는지 검증한다."""
    seed = _read(USER_URL_SEED_PATH)
    event_position = seed.index("INSERT INTO agent.wiki_source_events")
    document_position = seed.index("INSERT INTO agent.user_source_documents")

    assert event_position < document_position
    assert "mock-clipping-user" in seed
    assert "'28'" in seed
    assert "'user/28'" in seed
    assert "user-url-" in seed
    assert "'url'" in seed
    assert "ON CONFLICT (user_id, source_event_id) DO UPDATE" in seed
    assert "payload = event.payload || EXCLUDED.payload" in seed
    assert "ON CONFLICT (namespace_key, canonical_url)" in seed
    assert "metadata = document.metadata || EXCLUDED.metadata" in seed
    assert "INSERT INTO agent.user_source_document_versions" not in seed
    assert "status = 'received'" not in seed
    assert "error_code = NULL" not in seed


def test_database_schema_contract_is_available() -> None:
    """실제 PostgreSQL에서 실행할 Schema 계약 검사가 제공되는지 검증한다."""
    schema_check = _read(SCHEMA_CHECK_PATH)

    assert "vector extension is missing" in schema_check
    assert "HNSW embedding index is missing" in schema_check
    assert "single schema document index is missing" in schema_check
    assert "required structured Wiki column" in schema_check
    assert "agent-db schema contract passed" in schema_check


def test_database_rls_contract_is_available() -> None:
    """Runtime Role의 사용자 및 시스템 Scope를 검증하는 SQL이 제공되는지 확인한다."""
    rls_check = _read(RLS_CHECK_PATH)

    assert "CREATE ROLE agent_rls_contract_role NOLOGIN" in rls_check
    assert "user scope expected 1 row" in rls_check
    assert "user scope expected only own Wiki rows" in rls_check
    assert "user scope expected 1 readable global cache row" in rls_check
    assert "user scope deleted % global cache rows" in rls_check
    assert "system scope expected 1 global cache row" in rls_check
    assert "user scope expected 1 source row" in rls_check
    assert "user scope deleted % other-user source rows" in rls_check
    assert "user scope expected 1 Wiki relation" in rls_check
    assert "user scope expected 1 Wiki version document" in rls_check
    assert "system scope expected 2 Wiki relations" in rls_check
    assert "system scope expected 2 Wiki version documents" in rls_check
    assert "system scope expected 2 rows" in rls_check
    assert "ROLLBACK" in rls_check
