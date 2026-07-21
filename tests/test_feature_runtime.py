"""완료된 명세 기능 facade의 공통 실행 위임 계약을 검증한다."""

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from agent.bambi.api import (
    bambi_001,
    bambi_004,
    bambi_005,
    bambi_008,
    bambi_009,
    bambi_011,
    bambi_012,
    bambi_018,
    bambi_020,
    bambi_021,
)
from agent.wiki_builder.api import wba_001, wba_003
from app.routers.service.api import (
    svc_001,
    svc_002,
    svc_003,
    svc_008,
    svc_013,
    svc_014,
)
from app.routers.service_worker.api import sw_004, sw_009
from domain.interests.api import int_001, int_002, int_005, int_011
from domain.jobs.api import job_001, job_002, job_006, job_007, job_010
from domain.personal_wiki.documents.api import (
    pwiki_003,
    pwiki_006,
    pwiki_007,
    pwiki_008,
    pwiki_011,
)
from domain.personal_wiki.embeddings.api import pwe_001, pwe_002
from domain.personal_wiki.retrieval.api import prag_003, prag_006, prag_007
from domain.personal_wiki.source_events.api import wse_001, wse_011, wse_013
from infrastructure.persistence.api import db_002, db_003, db_004, db_005, db_026
from infrastructure.sources.connectors.api import col_002, col_003, col_004
from infrastructure.sources.processing.api import gsp_004, gsp_006, gsp_015
from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation
from workers.runtime.api import wc_002, wc_006, wc_009, wc_013

type FeatureDelegate = Callable[[FeatureRequest], Awaitable[FeatureResult]]

DELEGATED_FEATURES: tuple[tuple[str, FeatureDelegate], ...] = (
    ("SVC-001", svc_001),
    ("SVC-002", svc_002),
    ("SVC-003", svc_003),
    ("SVC-008", svc_008),
    ("SVC-013", svc_013),
    ("SVC-014", svc_014),
    ("SW-004", sw_004),
    ("SW-009", sw_009),
    ("WSE-001", wse_001),
    ("WSE-011", wse_011),
    ("WSE-013", wse_013),
    ("PWIKI-003", pwiki_003),
    ("PWIKI-006", pwiki_006),
    ("PWIKI-007", pwiki_007),
    ("PWIKI-008", pwiki_008),
    ("PWIKI-011", pwiki_011),
    ("PWE-001", pwe_001),
    ("PWE-002", pwe_002),
    ("PRAG-003", prag_003),
    ("PRAG-006", prag_006),
    ("PRAG-007", prag_007),
    ("INT-001", int_001),
    ("INT-002", int_002),
    ("INT-005", int_005),
    ("INT-011", int_011),
    ("COL-002", col_002),
    ("COL-003", col_003),
    ("COL-004", col_004),
    ("GSP-004", gsp_004),
    ("GSP-006", gsp_006),
    ("GSP-015", gsp_015),
    ("BAMBI-001", bambi_001),
    ("BAMBI-004", bambi_004),
    ("BAMBI-005", bambi_005),
    ("BAMBI-008", bambi_008),
    ("BAMBI-009", bambi_009),
    ("BAMBI-011", bambi_011),
    ("BAMBI-012", bambi_012),
    ("BAMBI-018", bambi_018),
    ("BAMBI-020", bambi_020),
    ("BAMBI-021", bambi_021),
    ("WBA-001", wba_001),
    ("WBA-003", wba_003),
    ("JOB-001", job_001),
    ("JOB-002", job_002),
    ("JOB-006", job_006),
    ("JOB-007", job_007),
    ("JOB-010", job_010),
    ("WC-002", wc_002),
    ("WC-006", wc_006),
    ("WC-009", wc_009),
    ("WC-013", wc_013),
    ("DB-002", db_002),
    ("DB-003", db_003),
    ("DB-004", db_004),
    ("DB-005", db_005),
    ("DB-026", db_026),
)


@pytest.mark.parametrize(("feature_id", "feature"), DELEGATED_FEATURES)
def test_completed_delegate_executes_injected_implementation(
    feature_id: str,
    feature: FeatureDelegate,
) -> None:
    """완료된 위임형 기능이 실제 구현을 실행하고 자기 ID를 보존한다."""
    result = asyncio.run(
        feature(
            FeatureRequest(
                request_id="request-1",
                payload={"implementation": lambda: {"value": feature_id}},
            )
        )
    )

    assert result == FeatureResult(feature_id=feature_id, data={"value": feature_id})


def test_feature_runtime_awaits_async_scalar_result() -> None:
    """비동기 구현의 일반 반환값을 result 필드로 정규화한다."""

    async def implementation() -> str:
        """비동기 실행 여부를 확인할 문자열을 반환한다."""
        return "completed"

    result = asyncio.run(
        execute_feature_implementation(
            FeatureRequest(
                request_id="request-1",
                payload={"implementation": implementation},
            ),
            feature_id="TEST-001",
        )
    )

    assert result == FeatureResult(
        feature_id="TEST-001",
        data={"result": "completed"},
    )


def test_feature_runtime_rejects_missing_implementation() -> None:
    """실행 구현이 없는 완료 기능 요청은 명시적인 입력 오류를 반환한다."""
    with pytest.raises(ValueError, match="TEST-001"):
        asyncio.run(
            execute_feature_implementation(
                FeatureRequest(request_id="request-1"),
                feature_id="TEST-001",
            )
        )


def test_feature_runtime_rejects_mismatched_feature_result() -> None:
    """다른 기능 ID의 결과가 경계를 넘어가는 것을 차단한다."""
    with pytest.raises(ValueError, match="OTHER-001"):
        asyncio.run(
            execute_feature_implementation(
                FeatureRequest(
                    request_id="request-1",
                    payload={
                        "implementation": lambda: FeatureResult(
                            feature_id="OTHER-001"
                        )
                    },
                ),
                feature_id="TEST-001",
            )
        )
