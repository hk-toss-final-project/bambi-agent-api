"""Wiki 관계 provenance·support·수명주기 Migration 계약을 검증한다."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    PROJECT_ROOT / "database" / "migrations" / "0017_wiki_relation_lifecycle.sql"
)
SCHEMA_CONTRACT_PATH = (
    PROJECT_ROOT / "database" / "checks" / "0001_schema_contract.sql"
)
RLS_CONTRACT_PATH = PROJECT_ROOT / "database" / "checks" / "0002_rls_contract.sql"


def _migration() -> str:
    """Wiki 관계 수명주기 Migration SQL을 읽는다."""
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_relation_lifecycle_migration_adds_head_state_and_trace() -> None:
    """관계 Head가 현재 판정과 Model·Prompt 추적 정보를 보존하는지 검증한다."""
    migration = _migration()

    assert "ALTER TABLE agent.wiki_document_relations" in migration
    for column in (
        "ADD COLUMN id uuid",
        "ADD COLUMN status text",
        "ADD COLUMN provenance_kind text",
        "ADD COLUMN confidence numeric(8,6)",
        "ADD COLUMN review_status text",
        "ADD COLUMN model_name text",
        "ADD COLUMN model_version text",
        "ADD COLUMN prompt_key text",
        "ADD COLUMN prompt_version text",
        "ADD COLUMN superseded_at timestamptz",
    ):
        assert column in migration
    assert "'source_explicit'" in migration
    assert "'semantic_inference'" in migration
    assert "'user_declared'" in migration
    assert "'system_rule'" in migration
    assert "DROP CONSTRAINT wiki_document_relations_relation_type_check" in migration
    for relation_type in (
        "instance_of",
        "subtopic_of",
        "part_of",
        "located_in",
        "occurs_in",
        "affects",
        "causes",
        "associated_with",
    ):
        assert f"'{relation_type}'" in migration
    assert "status = 'active' AND superseded_at IS NULL" in migration
    assert "status = 'superseded' AND superseded_at IS NOT NULL" in migration


def test_relation_lifecycle_migration_creates_source_support_history() -> None:
    """원본 Version·Build별 관계 support 이력과 Namespace FK를 검증한다."""
    migration = _migration()

    assert "CREATE TABLE agent.wiki_relation_supports" in migration
    assert "source_document_version_id uuid NOT NULL" in migration
    assert "build_job_id uuid NOT NULL REFERENCES agent.agent_jobs(id)" in migration
    assert "evidence text" in migration
    assert "UNIQUE (relation_id, source_document_version_id, build_job_id)" in migration
    assert "FOREIGN KEY (relation_id, namespace_key)" in migration
    assert "FOREIGN KEY (source_document_version_id, namespace_key)" in migration
    assert "ALTER TABLE agent.wiki_relation_supports ENABLE ROW LEVEL SECURITY" in migration
    assert "CREATE POLICY wiki_relation_support_read" in migration
    assert "CREATE POLICY wiki_relation_support_write" in migration
    assert "CREATE FUNCTION agent.supersede_wiki_relation_without_support()" in migration
    assert "AFTER DELETE ON agent.wiki_relation_supports" in migration
    assert "support.status = 'active'" in migration
    assert "VALUES (17, 'Track Wiki relation provenance supports and lifecycle')" in migration


def test_relation_support_is_covered_by_schema_and_rls_contracts() -> None:
    """관계 support 테이블을 필수 스키마와 사용자 격리 계약에서 검증한다."""
    schema_contract = SCHEMA_CONTRACT_PATH.read_text(encoding="utf-8")
    rls_contract = RLS_CONTRACT_PATH.read_text(encoding="utf-8")

    assert "'wiki_relation_supports'" in schema_contract
    assert "GRANT SELECT, DELETE ON agent.wiki_relation_supports" in rls_contract
    assert "system scope expected 2 Wiki relation supports" in rls_contract
