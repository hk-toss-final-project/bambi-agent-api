"""INT-005 관심사 점수 계산을 검증한다.

기본 점수(Wiki 구조 가중치 × 근거 강도 × 최신성 감쇠)와 그 위에 더해지는
행동 신호 보정을 함께 검증한다.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from domain.interests.api import int_005
from shared.wiki_models import InterestCandidate

_NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _candidate(
    topic: str,
    *,
    structure_weight: float = 2.0,
    source_count: int = 1,
    source_types: list[str] | None = None,
    last_activity_at: str | None = "2026-07-27T12:00:00+00:00",
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


def _signal_candidate(
    topic: str, *, weight: float, score: float = 1.0
) -> InterestCandidate:
    """행동 신호 검증용 Wiki 반복도 기반 후보 한 건을 만든다."""
    return InterestCandidate(
        topic=topic,
        category="method",
        score=score,
        confidence=0.6,
        document_ids=("doc-1",),
        evidence={"weight": weight, "reasons": ["title"]},
    )


# --- 기본 점수(Wiki 근거 기반) ---


def test_int_005_prefers_recent_interests() -> None:
    """구조 점수가 같으면 최근에 활동한 관심사가 앞서는지 검증한다."""
    scored = asyncio.run(
        int_005(
            [
                _candidate("오래된 주제", last_activity_at="2025-07-27T12:00:00+00:00"),
                _candidate("최근 주제", last_activity_at="2026-07-27T12:00:00+00:00"),
            ],
            now=_NOW,
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
            [_candidate("주제", last_activity_at="2026-04-28T12:00:00+00:00")],
            now=_NOW,
            limit=10,
            half_life_days=90.0,
        )
    )

    assert scored[0].evidence["recency_factor"] == pytest.approx(0.5, abs=0.01)


def test_int_005_ranks_onboarding_seed_below_real_source() -> None:
    """다른 조건이 같으면 온보딩 씨앗이 실제 저장 근거보다 낮게 매겨지는지 검증한다."""
    scored = asyncio.run(
        int_005(
            [
                _candidate("씨앗 주제", source_types=["onboarding_seed"]),
                _candidate("클리핑 주제", source_types=["web_clipping"]),
            ],
            now=_NOW,
            limit=10,
        )
    )

    assert [candidate.topic for candidate in scored] == ["클리핑 주제", "씨앗 주제"]
    seed = next(c for c in scored if c.topic == "씨앗 주제")
    real = next(c for c in scored if c.topic == "클리핑 주제")
    assert seed.evidence["behavior_intensity"] < real.evidence["behavior_intensity"]


def test_int_005_rewards_stronger_user_behavior() -> None:
    """직접 작성한 근거가 있는 관심사가 단순 클리핑보다 높은지 검증한다."""
    scored = asyncio.run(
        int_005(
            [
                _candidate("클리핑만", source_types=["web_clipping"]),
                _candidate("직접 작성", source_types=["memo"]),
            ],
            now=_NOW,
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
        int_005([_candidate("시각 없음", last_activity_at=None)], now=_NOW, limit=10)
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
            now=_NOW,
            limit=2,
        )
    )

    assert [candidate.topic for candidate in scored] == ["첫째", "둘째"]
    assert scored[0].evidence["structure_weight"] == 3.0
    assert scored[0].evidence["scored_at"] == _NOW.isoformat()


def test_int_005_validates_arguments_and_empty_input() -> None:
    """잘못된 limit·반감기를 거절하고 빈 입력은 빈 목록을 반환하는지 검증한다."""
    assert asyncio.run(int_005([], now=_NOW)) == []
    with pytest.raises(ValueError, match="limit"):
        asyncio.run(int_005([_candidate("주제")], limit=0))
    with pytest.raises(ValueError, match="반감기"):
        asyncio.run(int_005([_candidate("주제")], half_life_days=0))


# --- 행동 신호 보정 ---


def test_like_signal_boosts_matching_topic() -> None:
    """좋아요 신호가 같은 Topic 후보의 점수를 끌어올리는지 검증한다."""
    candidates = [
        _signal_candidate("LangGraph", weight=5.0),
        _signal_candidate("PostgreSQL", weight=5.0),
    ]
    signals = [
        {"topic": "langgraph", "signal_type": "like", "occurred_at": _NOW},
        {"topic": "LangGraph", "signal_type": "like", "occurred_at": _NOW},
    ]

    result = asyncio.run(int_005(candidates, signals=signals, now=_NOW))

    assert result[0].topic == "LangGraph"
    assert result[0].score == 1.0
    postgres = next(item for item in result if item.topic == "PostgreSQL")
    assert postgres.score < 1.0
    assert result[0].confidence > 0.6
    assert "behavior:like" in result[0].evidence["reasons"]


def test_signal_weight_decays_over_time() -> None:
    """반감기(14일)가 지난 신호의 보정치가 절반으로 줄어드는지 검증한다."""
    fresh = asyncio.run(
        int_005(
            [_signal_candidate("A", weight=1.0)],
            signals=[{"topic": "A", "signal_type": "like", "occurred_at": _NOW}],
            now=_NOW,
        )
    )
    aged = asyncio.run(
        int_005(
            [_signal_candidate("A", weight=1.0)],
            signals=[
                {
                    "topic": "A",
                    "signal_type": "like",
                    "occurred_at": _NOW - timedelta(days=14),
                }
            ],
            now=_NOW,
        )
    )

    fresh_boost = float(fresh[0].evidence["behavior_boost"])
    aged_boost = float(aged[0].evidence["behavior_boost"])
    assert fresh_boost == 1.0
    assert abs(aged_boost - 0.5) < 1e-6


def test_negative_signal_lowers_topic_weight() -> None:
    """숨김·신고 같은 부정 신호가 Topic 가중치를 낮추는지 검증한다."""
    candidates = [
        _signal_candidate("Crypto", weight=5.0),
        _signal_candidate("LangGraph", weight=4.0),
    ]
    signals = [
        {"topic": "Crypto", "signal_type": "report", "occurred_at": _NOW},
        {"topic": "Crypto", "signal_type": "hide", "occurred_at": _NOW},
    ]

    result = asyncio.run(int_005(candidates, signals=signals, now=_NOW))

    assert result[0].topic == "LangGraph"
    crypto = next(item for item in result if item.topic == "Crypto")
    assert crypto.score < result[0].score


def test_behavior_only_topic_becomes_new_candidate() -> None:
    """Wiki에 없는 Topic의 양의 신호가 행동 전용 후보를 만드는지 검증한다."""
    result = asyncio.run(
        int_005(
            [_signal_candidate("LangGraph", weight=5.0)],
            signals=[{"topic": "Rust", "signal_type": "like", "occurred_at": _NOW}],
            now=_NOW,
        )
    )

    rust = next(item for item in result if item.topic == "Rust")
    assert rust.document_ids == ()
    assert rust.evidence["reasons"] == ["behavior:like"]
    assert 0 < rust.score < 1.0


def test_unknown_signal_type_and_empty_signals_add_no_boost() -> None:
    """알 수 없는 신호 유형과 빈 신호가 행동 보정을 만들지 않는지 검증한다.

    기본 점수는 신호와 무관하게 항상 계산하므로, 후보가 그대로 반환되는지가
    아니라 behavior_boost가 붙지 않는지를 확인한다.
    """
    candidates = [_signal_candidate("LangGraph", weight=5.0)]

    unknown = asyncio.run(
        int_005(
            candidates,
            signals=[{"topic": "LangGraph", "signal_type": "view"}],
            now=_NOW,
        )
    )
    empty = asyncio.run(int_005(candidates, signals=[], now=_NOW))

    assert [item.topic for item in unknown] == ["LangGraph"]
    assert "behavior_boost" not in unknown[0].evidence
    assert [item.topic for item in empty] == ["LangGraph"]
    assert "behavior_boost" not in empty[0].evidence
    assert unknown[0].confidence == empty[0].confidence == 0.6
