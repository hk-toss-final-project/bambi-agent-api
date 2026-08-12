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
INTEREST_TAXONOMY_MIGRATION_PATH = (
    PROJECT_ROOT
    / "database"
    / "migrations"
    / "0011_interest_taxonomy_pipeline.sql"
)
CHANGE_HISTORY_MIGRATION_PATH = (
    PROJECT_ROOT
    / "database"
    / "migrations"
    / "0015_change_history_delta.sql"
)
DUPLICATED_VERSION_REPAIR_MIGRATION_PATH = (
    PROJECT_ROOT
    / "database"
    / "migrations"
    / "0016_reconcile_duplicated_version_12.sql"
)
WIKI_RELATION_LIFECYCLE_MIGRATION_PATH = (
    PROJECT_ROOT
    / "database"
    / "migrations"
    / "0017_wiki_relation_lifecycle.sql"
)
PERSONAL_WIKI_RESET_MIGRATION_PATH = (
    PROJECT_ROOT
    / "database"
    / "migrations"
    / "0018_personal_wiki_reset.sql"
)
ONBOARDING_CONTEXT_MIGRATION_PATH = (
    PROJECT_ROOT
    / "database"
    / "migrations"
    / "0019_onboarding_topic_contexts.sql"
)
PROVIDER_RATE_GOVERNOR_MIGRATION_PATH = (
    PROJECT_ROOT / "database" / "migrations" / "0023_openai_rate_governor.sql"
)
OPENAI_BATCH_MIGRATION_PATH = (
    PROJECT_ROOT / "database" / "migrations" / "0024_openai_batch_jobs.sql"
)
WAITING_PROVIDER_MIGRATION_PATH = (
    PROJECT_ROOT / "database" / "migrations" / "0025_waiting_provider_jobs.sql"
)
GLOBAL_SOURCE_IMAGE_MIGRATION_PATH = (
    PROJECT_ROOT / "database" / "migrations" / "0026_global_source_image_url.sql"
)
BRIEFING_SNAPSHOT_MIGRATION_PATH = (
    PROJECT_ROOT / "database" / "migrations" / "0028_briefing_topic_snapshots.sql"
)
COLLECTION_TARGET_POLICY_MIGRATION_PATH = (
    PROJECT_ROOT
    / "database"
    / "migrations"
    / "0029_collection_target_budget_policy.sql"
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
    CHANGE_HISTORY_MIGRATION_PATH,
    DUPLICATED_VERSION_REPAIR_MIGRATION_PATH,
    WIKI_RELATION_LIFECYCLE_MIGRATION_PATH,
    PERSONAL_WIKI_RESET_MIGRATION_PATH,
    ONBOARDING_CONTEXT_MIGRATION_PATH,
    PROVIDER_RATE_GOVERNOR_MIGRATION_PATH,
    OPENAI_BATCH_MIGRATION_PATH,
    WAITING_PROVIDER_MIGRATION_PATH,
    GLOBAL_SOURCE_IMAGE_MIGRATION_PATH,
    BRIEFING_SNAPSHOT_MIGRATION_PATH,
    COLLECTION_TARGET_POLICY_MIGRATION_PATH,
)
SCHEMA_CHECK_PATH = PROJECT_ROOT / "database" / "checks" / "0001_schema_contract.sql"
RLS_CHECK_PATH = PROJECT_ROOT / "database" / "checks" / "0002_rls_contract.sql"
DESIGN_PATH = PROJECT_ROOT / "docs" / "agent-db-design.md"
TABLE_CATALOG_PATH = PROJECT_ROOT / "docs" / "agent-db-table-catalog.md"
COLUMN_DICTIONARY_PATH = PROJECT_ROOT / "docs" / "agent-db-column-dictionary.md"
COMPOSE_PATH = PROJECT_ROOT / "compose.yaml"
DATABASE_README_PATH = PROJECT_ROOT / "database" / "README.md"
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
    table_names = set(
        re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?agent\.([a-z_]+)", migration)
    )
    required_tables = {
        "user_context_snapshots",
        "wiki_source_events",
        "user_source_documents",
        "user_source_document_versions",
        "wiki_documents",
        "wiki_document_versions",
        "wiki_document_sources",
        "wiki_document_relations",
        "wiki_relation_supports",
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
        "provider_rate_limits",
        "llm_batches",
        "llm_batch_items",
        "briefing_topic_snapshots",
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


def test_interest_taxonomy_migration_adds_snapshots_targets_and_subscriptions() -> None:
    """taxonomy 복제·Topic 수집·사용자 구독 테이블과 스케줄 Source를 검증한다."""
    migration = _read(INTEREST_TAXONOMY_MIGRATION_PATH)

    assert "CREATE TABLE agent.interest_taxonomy_versions" in migration
    assert "CREATE TABLE agent.interest_taxonomy_categories" in migration
    assert "CREATE TABLE agent.interest_taxonomy_topics" in migration
    assert "CREATE TABLE agent.interest_collection_targets" in migration
    assert "CREATE TABLE agent.user_interest_subscriptions" in migration
    assert "CREATE TABLE agent.global_source_document_topics" in migration
    assert "'interest-taxonomy-google-news'" in migration
    assert "VALUES (11," in migration


def test_collection_target_policy_migration_reconciles_existing_targets() -> None:
    """기존 수집 대상도 구독 수·주기·하루 처리량 정책으로 한 번에 정리한다."""
    migration = _read(COLLECTION_TARGET_POLICY_MIGRATION_PATH)

    assert "WHEN policy.subscriber_count = 0 THEN 'paused'" in migration
    assert "WHEN counts.subscriber_count >= 10 THEN 360" in migration
    assert "WHEN counts.subscriber_count >= 5 THEN 720" in migration
    assert "/ 250.0" in migration
    assert "VALUES (29," in migration


def test_onboarding_context_migration_seeds_all_topics_and_custom_cache() -> None:
    """44개 정식 Topic 컨텍스트·사용자 캐시·단일 활성 시드 Head를 검증한다."""
    migration = _read(ONBOARDING_CONTEXT_MIGRATION_PATH)
    topic_ids = re.findall(
        r"^\('1\.0\.0-draft', '([^']+)'",
        migration,
        flags=re.MULTILINE,
    )

    assert "CREATE TABLE agent.onboarding_topic_contexts" in migration
    assert "CREATE TABLE agent.user_custom_topic_contexts" in migration
    assert "uq_user_source_documents_active_onboarding_seed" in migration
    assert "status = 'superseded'" in migration
    assert len(topic_ids) == 44
    assert len(set(topic_ids)) == 44
    assert "'ai_ml'" in migration and "'pet'" in migration
    assert "VALUES (19," in migration


def test_change_history_migration_adds_delta_facts_idempotently() -> None:
    """델타 팩트·실행 테이블을 기존 데이터 손실 없이 멱등 추가하는지 검증한다.

    중복된 version 12 중 change_history 쪽이 먼저 실행된 DB에서는 테이블·색인·
    정책·Trigger가 이미 존재한다. 0015는 그 상태에서도 안전하게 version 15를
    기록해야 하며 다른 기능 영역의 테이블은 변경하지 않는다.
    """
    migration = _read(CHANGE_HISTORY_MIGRATION_PATH)

    assert "CREATE TABLE IF NOT EXISTS agent.change_history_runs" in migration
    assert "CREATE TABLE IF NOT EXISTS agent.change_history_facts" in migration
    assert "CREATE INDEX IF NOT EXISTS ix_change_history_runs_latest" in migration
    assert "CREATE INDEX IF NOT EXISTS ix_change_history_facts_scope" in migration
    assert "DROP POLICY IF EXISTS change_history_run_isolation" in migration
    assert "DROP POLICY IF EXISTS change_history_fact_isolation" in migration
    assert "DROP TRIGGER IF EXISTS set_change_history_facts_updated_at" in migration
    # 갱신 관계는 자기참조 링크로 남기고, before 문구는 이 링크로 DB에서 읽는다.
    assert "supersedes_fact_id uuid REFERENCES agent.change_history_facts(id)" in migration
    assert "change_history_fact_isolation" in migration
    assert "agent.current_user_id()" in migration
    # 0012_global_source_search_body.sql과 번호가 겹쳐 0015로 옮겼다.
    assert "VALUES (15," in migration
    assert "ALTER TABLE" not in migration.replace(
        "ALTER TABLE agent.change_history_runs ENABLE ROW LEVEL SECURITY", ""
    ).replace("ALTER TABLE agent.change_history_facts ENABLE ROW LEVEL SECURITY", "")


def test_duplicated_version_repair_restores_skipped_search_body_schema() -> None:
    """version 12를 delta가 선점한 DB의 누락된 검색 본문 Schema를 복구한다."""
    migration = _read(DUPLICATED_VERSION_REPAIR_MIGRATION_PATH)

    assert "information_schema.columns" in migration
    assert "AS should_repair_search_body" in migration
    assert r"\if :should_repair_search_body" in migration
    assert "ADD COLUMN IF NOT EXISTS search_body text" in migration
    assert "DROP COLUMN IF EXISTS search_vector" in migration
    assert "coalesce(search_body, markdown, '')" in migration
    assert "ix_global_source_documents_search_body_trgm" in migration
    assert "VALUES (16," in migration


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


def test_provider_rate_governor_migration_tracks_rpm_tpm_and_blocking() -> None:
    """Provider Rate Governor가 요청·Token·차단 상태를 공유하는지 검증한다."""
    migration = _read(PROVIDER_RATE_GOVERNOR_MIGRATION_PATH)

    assert "CREATE TABLE agent.provider_rate_limits" in migration
    assert "PRIMARY KEY (provider, resource_key)" in migration
    assert "remaining_requests bigint" in migration
    assert "remaining_tokens bigint" in migration
    assert "blocked_until timestamptz" in migration
    assert "VALUES (23," in migration


def test_openai_batch_migration_tracks_custom_id_files_and_domain_lease() -> None:
    """OpenAI Batch가 파일·custom_id·부분 결과·도메인 반영 Lease를 보존한다."""
    migration = _read(OPENAI_BATCH_MIGRATION_PATH)

    assert "CREATE TABLE agent.llm_batches" in migration
    assert "CREATE TABLE agent.llm_batch_items" in migration
    assert "custom_id text NOT NULL UNIQUE" in migration
    assert "provider_batch_id text UNIQUE" in migration
    assert "output_file_id text" in migration
    assert "error_file_id text" in migration
    assert "domain_apply_claimed_at timestamptz" in migration
    assert "completion_window = '24h'" in migration
    assert "VALUES (24," in migration


def test_waiting_provider_migration_releases_long_running_job_lease() -> None:
    """OpenAI Batch 대기 Job 상태와 운영 조회 Index가 추가되는지 검증한다."""
    migration = _read(WAITING_PROVIDER_MIGRATION_PATH)

    assert "'waiting_provider'" in migration
    assert "DROP CONSTRAINT agent_jobs_status_check" in migration
    assert "ix_agent_jobs_waiting_provider" in migration
    assert "VALUES (25," in migration


def test_briefing_snapshot_migration_tracks_topics_evidence_and_rls() -> None:
    """브리핑 Snapshot이 날짜별 주제·근거와 사용자 격리를 보존한다."""
    migration = _read(BRIEFING_SNAPSHOT_MIGRATION_PATH)

    assert "CREATE TABLE agent.briefing_topic_snapshots" in migration
    assert "UNIQUE (user_id, briefing_date)" in migration
    assert "contexts_by_topic jsonb" in migration
    assert "prepared_by_job_id uuid" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "briefing_topic_snapshot_isolation" in migration
    assert "VALUES (28," in migration


def test_migration_does_not_create_service_owned_tables() -> None:
    """Agent DB가 Service 계층 소유 Table을 생성하지 않는지 검증한다."""
    migration = _read(MIGRATION_PATH)
    service_owned_tables = {"users", "bookmarks", "cards", "feed_items", "likes"}
    created_tables = set(
        re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?agent\.([a-z_]+)", migration)
    )

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
    created_tables = set(
        re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?agent\.([a-z_]+)", migration)
    )
    catalog_rows = re.findall(r"^\| ([a-z][a-z_]*) \|", catalog, re.MULTILINE)

    assert len(catalog_rows) == len(set(catalog_rows))
    assert set(catalog_rows) == created_tables


def test_column_dictionary_documents_every_migration_column() -> None:
    """컬럼 사전이 모든 Migration의 Table과 Column을 정확히 문서화하는지 검증한다."""
    expected: dict[str, set[str]] = {}

    for migration_path in MIGRATION_PATHS:
        migration = _read(migration_path)
        for match in re.finditer(
            r"CREATE TABLE (?:IF NOT EXISTS )?agent\.([a-z_]+) \((.*?)\n\);",
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
    """Compose가 DB 시작마다 Migration Initializer를 실행하는지 검증한다."""
    compose = _read(COMPOSE_PATH)

    # PostgreSQL 17.9 미만은 UTF-8 본문 substring()이 깨진다(BUG #19406).
    assert "pgvector/pgvector:0.8.5-pg17-bookworm" in compose
    assert "AGENT_DB_PASSWORD:?" in compose
    assert "127.0.0.1:${AGENT_DB_PORT:-5432}:5432" in compose
    assert "./database/migrations:/opt/bambi/migrations:ro" in compose
    assert "database/seeds" not in compose
    assert "AGENT_DB_APPLY_DEV_SEEDS" not in compose
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


def _migration_files() -> list[Path]:
    """실행 대상이 되는 Migration 파일을 Runner와 같은 이름 규칙으로 모은다."""
    directory = PROJECT_ROOT / "database" / "migrations"
    return sorted(path for path in directory.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def test_migration_file_numbers_are_unique() -> None:
    """Migration 번호가 겹치지 않는지 검증한다.

    Runner는 파일 이름의 숫자로만 적용 여부를 판단하고 schema_migrations.version은
    Primary Key라, 같은 번호가 둘이면 뒤엣것이 "이미 적용됨"으로 조용히 건너뛰어져
    운영 DB에 영영 반영되지 않는다(2026-08-07에 0012가 둘이라 실제로 발생).
    """
    numbers = [path.name.split("_")[0] for path in _migration_files()]
    duplicates = sorted({number for number in numbers if numbers.count(number) > 1})

    assert duplicates == [], f"Migration 번호가 겹칩니다: {duplicates}"


def test_every_migration_records_its_own_version() -> None:
    """모든 Migration이 파일 이름과 같은 version을 트랜잭션 안에서 기록하는지 검증한다.

    Runner는 파일을 적용한 뒤 그 version이 schema_migrations에 남았는지 확인하고,
    없으면 예외로 멈춘다. 기록을 빠뜨리면 DB 초기화 전체가 실패한다.
    """
    missing: list[str] = []
    mismatched: list[str] = []
    not_transactional: list[str] = []

    for path in _migration_files():
        expected = int(path.name.split("_")[0])
        body = _read(path)
        recorded = re.search(
            r"INSERT INTO agent\.schema_migrations\s*\(version, description\)\s*"
            r"VALUES\s*\((\d+)",
            body,
        )
        if recorded is None:
            missing.append(path.name)
            continue
        if int(recorded.group(1)) != expected:
            mismatched.append(f"{path.name} -> {recorded.group(1)}")
        if "BEGIN;" not in body or "COMMIT;" not in body:
            not_transactional.append(path.name)

    assert missing == [], f"schema_migrations 기록이 없습니다: {missing}"
    assert mismatched == [], f"파일 이름과 기록된 version이 다릅니다: {mismatched}"
    assert not_transactional == [], f"트랜잭션이 없습니다: {not_transactional}"


def test_personal_wiki_reset_migration_blocks_cancelled_build_writes() -> None:
    """초기화와 경합한 취소 Build가 Wiki Version을 저장하지 못하는지 검증한다."""
    migration = _read(PERSONAL_WIKI_RESET_MIGRATION_PATH)

    assert "'onboarding_seed', 'reset'" in migration
    assert "CREATE FUNCTION agent.reject_cancelled_wiki_build()" in migration
    assert "job.status = 'cancelled'" in migration
    assert "ON agent.wiki_document_versions" in migration


def test_database_initializer_runs_only_migrations() -> None:
    """DB 초기화 경로가 Migration Runner만 실행하는지 검증한다."""
    initializer = _read(DATABASE_INITIALIZER_PATH)

    assert '/bin/sh "$migration_runner" "$MODE"' in initializer
    assert "AGENT_DB_MIGRATION_RUNNER_PATH" in initializer
    assert "SEED" not in initializer


def test_database_initializer_delegates_check_mode_to_migration_runner(
    tmp_path: Path,
) -> None:
    """배포 Initializer가 검증 모드를 Migration Runner에 그대로 전달한다."""
    runner = tmp_path / "migration-runner.sh"
    runner.write_text('#!/bin/sh\nprintf \'%s\\n\' "$1"\n', encoding="utf-8")
    environment = os.environ.copy()
    environment["AGENT_DB_MIGRATION_RUNNER_PATH"] = str(runner)

    result = subprocess.run(
        ["/bin/sh", str(DATABASE_INITIALIZER_PATH), "--check"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "--check"


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
    assert "AGENT_DB_MIGRATION_DIR=/app/database/migrations" in readme
    assert "AGENT_DB_SEED" not in readme
    assert "API·Worker를 먼저 기동하지 않습니다" in readme


def test_project_readme_uses_database_starter() -> None:
    """프로젝트 실행 안내가 반복 가능한 Agent DB 시작 명령을 사용하는지 검증한다."""
    readme = _read(PROJECT_README_PATH)

    assert "./scripts/start_agent_db.sh" in readme
    assert "이미 실행 중인 DB에도" in readme



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
