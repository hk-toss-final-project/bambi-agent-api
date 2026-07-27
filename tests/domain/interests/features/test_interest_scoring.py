"""INT-005 행동 신호 점수 보정을 검증한다."""

import asyncio
from datetime import UTC, datetime, timedelta

from domain.interests.api import int_005
from shared.wiki_models import InterestCandidate


_NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _candidate(topic: str, *, weight: float, score: float = 1.0) -> InterestCandidate:
    """Wiki 반복도 기반 후보 한 건을 만든다."""
    return InterestCandidate(
        topic=topic,
        category="method",
        score=score,
        confidence=0.6,
        document_ids=("doc-1",),
        evidence={"weight": weight, "reasons": ["title"]},
    )


def test_like_signal_boosts_matching_topic() -> None:
    """좋아요 신호가 같은 Topic 후보의 점수를 끌어올리는지 검증한다."""
    candidates = [
        _candidate("LangGraph", weight=5.0),
        _candidate("PostgreSQL", weight=5.0),
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
            [_candidate("A", weight=1.0)],
            signals=[{"topic": "A", "signal_type": "like", "occurred_at": _NOW}],
            now=_NOW,
        )
    )
    aged = asyncio.run(
        int_005(
            [_candidate("A", weight=1.0)],
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
        _candidate("Crypto", weight=5.0),
        _candidate("LangGraph", weight=4.0),
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
            [_candidate("LangGraph", weight=5.0)],
            signals=[
                {"topic": "Rust", "signal_type": "like", "occurred_at": _NOW},
            ],
            now=_NOW,
        )
    )

    rust = next(item for item in result if item.topic == "Rust")
    assert rust.document_ids == ()
    assert rust.evidence["reasons"] == ["behavior:like"]
    assert 0 < rust.score < 1.0


def test_unknown_signal_type_and_empty_signals_are_ignored() -> None:
    """알 수 없는 신호 유형과 빈 신호가 후보를 바꾸지 않는지 검증한다."""
    candidates = [_candidate("LangGraph", weight=5.0)]

    unchanged = asyncio.run(
        int_005(
            candidates,
            signals=[{"topic": "LangGraph", "signal_type": "view"}],
            now=_NOW,
        )
    )
    empty = asyncio.run(int_005(candidates, signals=[], now=_NOW))

    assert unchanged == list(candidates)
    assert empty == list(candidates)
