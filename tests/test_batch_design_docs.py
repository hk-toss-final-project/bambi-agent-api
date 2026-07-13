"""MVP Batch 처리 설계 문서의 상호 정합성을 검증한다."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEATURE_SPEC = ROOT / "docs" / "agent-api-feature-spec.md"
MVP_SCOPE = ROOT / "docs" / "agent-api-mvp-scope.md"
FASTAPI_SPEC = ROOT / "docs" / "fastapi-mvp-api.md"
DB_DESIGN = ROOT / "docs" / "agent-db-design.md"


def _read(path: Path) -> str:
    """UTF-8 문서 내용을 반환한다."""
    return path.read_text(encoding="utf-8")


def test_feature_spec_assigns_batch_responsibilities_to_existing_ids() -> None:
    """기존 Worker·Service Worker 기능 ID가 Batch 책임을 포함하는지 검증한다."""
    feature_spec = _read(FEATURE_SPEC)

    assert "| WC-002 | Job Claim |" in feature_spec
    assert "작업 Batch를 Lease와 함께 점유" in feature_spec
    assert "| SW-004 | Publish Snapshot 조회 |" in feature_spec
    assert "준비된 Snapshot Batch를 Claim" in feature_spec
    assert "| SW-009 | 발행 완료 ACK |" in feature_spec
    assert "부분 성공 ACK" in feature_spec


def test_mvp_scope_includes_generation_and_publish_batch_flow() -> None:
    """MVP 범위가 Agent 생성과 Service Worker 발행 Batch를 모두 포함하는지 검증한다."""
    mvp_scope = _read(MVP_SCOPE)

    assert "### MVP Batch 처리 계약" in mvp_scope
    assert "FOR UPDATE SKIP LOCKED" in mvp_scope
    assert "Batch Claim 크기와 실제 LLM 호출 동시성" in mvp_scope
    assert "부분 성공 Batch ACK" in mvp_scope


def test_fastapi_spec_defines_batch_claim_and_ack_contracts() -> None:
    """FastAPI MVP 문서에 Batch Claim과 ACK 경로 및 부분 성공 계약이 있는지 검증한다."""
    fastapi_spec = _read(FASTAPI_SPEC)

    assert "/internal/v1/publish-snapshot-batches/claim" in fastapi_spec
    assert "/internal/v1/publish-snapshot-batches/{batch_id}/ack" in fastapi_spec
    assert "PUBLISH_BATCH_OWNERSHIP_MISMATCH" in fastapi_spec
    assert "PUBLISH_BATCH_LEASE_EXPIRED" in fastapi_spec
    assert '"retry_scheduled_count"' in fastapi_spec


def test_db_design_defines_claim_lease_and_retry_state() -> None:
    """DB 설계가 Job·Snapshot Claim Lease와 재시도 상태를 정의하는지 검증한다."""
    db_design = _read(DB_DESIGN)

    assert "### Agent Job Batch Claim" in db_design
    assert "### Publish Snapshot Batch Claim과 ACK" in db_design
    assert "FOR UPDATE SKIP LOCKED" in db_design
    assert "lease_expires_at timestamptz" in db_design
    assert "next_attempt_at timestamptz" in db_design
