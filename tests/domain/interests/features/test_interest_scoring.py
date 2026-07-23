"""INT-005 관심사 점수 계산 규칙을 검증한다."""

import asyncio
from datetime import UTC, datetime

import pytest

from domain.interests.api import int_005
from shared.wiki_models import InterestCandidate

_NOW = datetime(2026, 7, 23, tzinfo=UTC)


def _candidate(
    topic: str,
    *,
    structure_weight: float = 2.0,
    source_count: int = 1,
    source_types: list[str] | None = None,
    last_activity_at: str | None = "2026-07-23T00:00:00+00:00",
) -> InterestCandidate:
    """검증용 INT-001 관심 후보를 만든다."""
    return InterestCandidate(
        topic=topic,
        category=None,
        score=1.0,
        confidence=0.5,
        document_ids=(f"{topic}-doc",),
        evidence={
            "structure_weight": structure_weight,
            "source_count": source_count,
            "source_types": source_types or ["web_clipping"],
            "last_activity_at": last_activity_at,
        },
    )


def test_int_005_prefers_recent_interests() -> None:
    """구조 점수가 같으면 최근에 활동한 관심사가 앞서는지 검증한다."""
    scored = asyncio.run(
        int_005(
            [
                _candidate("오래된 주제", last_activity_at="2025-07-23T00:00:00+00:00"),
                _candidate("최근 주제", last_activity_at="2026-07-23T00:00:00+00:00"),
            ],
            reference_time=_NOW,
            limit=10,
        )
    )

    assert [candidate.topic for candidate in scored] == ["최근 주제", "오래된 주제"]
    assert scored[0].score == 1.0
    assert scored[1].score < scored[0].score


def test_int_005_applies_half_life_decay() -> None:
    """반감기만큼 지난 관심사의 감쇠 계수가 0.5가 되는지 검증한다."""
    scored = asyncio.run(
        int_005(
            [_candidate("주제", last_activity_at="2026-04-24T00:00:00+00:00")],
            reference_time=_NOW,
            limit=10,
            half_life_days=90.0,
        )
    )

    assert scored[0].evidence["recency_factor"] == pytest.approx(0.5, abs=0.01)


def test_int_005_rewards_stronger_user_behavior() -> None:
    """직접 작성한 근거가 있는 관심사가 단순 클리핑보다 높은지 검증한다."""
    scored = asyncio.run(
        int_005(
            [
                _candidate("클리핑만", source_types=["web_clipping"]),
                _candidate("직접 작성", source_types=["memo"]),
            ],
            reference_time=_NOW,
            limit=10,
        )
    )

    assert scored[0].topic == "직접 작성"
    assert (
        scored[0].evidence["behavior_intensity"]
        > scored[1].evidence["behavior_intensity"]
    )


def test_int_005_uses_neutral_recency_without_activity_time() -> None:
    """활동 시각을 모르면 중립 감쇠 계수를 적용하는지 검증한다."""
    scored = asyncio.run(
        int_005(
            [_candidate("시각 없음", last_activity_at=None)],
            reference_time=_NOW,
            limit=10,
        )
    )

    assert scored[0].evidence["recency_factor"] == 0.5


def test_int_005_keeps_extraction_evidence_and_limits_results() -> None:
    """INT-001 근거를 보존하면서 상위 limit개만 반환하는지 검증한다."""
    scored = asyncio.run(
        int_005(
            [
                _candidate("첫째", structure_weight=3.0),
                _candidate("둘째", structure_weight=2.0),
                _candidate("셋째", structure_weight=1.0),
            ],
            reference_time=_NOW,
            limit=2,
        )
    )

    assert [candidate.topic for candidate in scored] == ["첫째", "둘째"]
    assert scored[0].evidence["structure_weight"] == 3.0
    assert scored[0].evidence["scored_at"] == _NOW.isoformat()


def test_int_005_validates_arguments_and_empty_input() -> None:
    """잘못된 limit·반감기를 거절하고 빈 입력은 빈 목록을 반환하는지 검증한다."""
    assert asyncio.run(int_005([], reference_time=_NOW)) == []
    with pytest.raises(ValueError, match="limit"):
        asyncio.run(int_005([_candidate("주제")], limit=0))
    with pytest.raises(ValueError, match="반감기"):
        asyncio.run(int_005([_candidate("주제")], half_life_days=0))
