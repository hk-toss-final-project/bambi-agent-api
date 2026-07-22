"""Report Builder 호환 공통 실행기와 타입 기반 facade 전환 경계를 검증한다."""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from agent.report_builder.api import (
    report_001,
    report_004,
    report_005,
    report_008,
    report_009,
    report_011,
    report_012,
    report_018,
    report_020,
    report_021,
)
from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation

type FeatureDelegate = Callable[[FeatureRequest], Awaitable[FeatureResult]]

DELEGATED_FEATURES: tuple[tuple[str, FeatureDelegate], ...] = (
    ("REPORT-001", report_001),
    ("REPORT-004", report_004),
    ("REPORT-005", report_005),
    ("REPORT-008", report_008),
    ("REPORT-009", report_009),
    ("REPORT-011", report_011),
    ("REPORT-012", report_012),
    ("REPORT-018", report_018),
    ("REPORT-020", report_020),
    ("REPORT-021", report_021),
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


def test_generic_executor_is_limited_to_excluded_report_features() -> None:
    """공통 구현 주입 실행기가 제외 대상 Report Builder 밖에서 사용되지 않는지 검증한다."""
    root = Path(__file__).resolve().parents[1]
    source_roots = ("app", "agent", "domain", "infrastructure", "workers", "scheduler")
    offending: list[str] = []
    for source_root in source_roots:
        for path in (root / source_root).rglob("*.py"):
            relative = path.relative_to(root)
            if relative.parts[:2] == ("agent", "report_builder"):
                continue
            if "execute_feature_implementation" in path.read_text(encoding="utf-8"):
                offending.append(str(relative))
    assert offending == []


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
