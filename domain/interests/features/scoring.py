"""기능 구현 모듈.

INT-005, INT-006, INT-008, INT-009 기능의 실제 구현 위치를 제공한다.

INT-005는 좋아요·숨김 같은 사용자 행동 신호에 시간 감쇠를 적용해
Wiki 반복도 기반 후보(INT-001)의 점수를 보정한다. LLM 없이 결정적으로
계산하며, 신호 가중치·반감기는 팀 확정 전 잠정값(D2)이다.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from shared.contracts import FeatureRequest, FeatureResult
from shared.wiki_models import InterestCandidate

# D2 잠정값(팀 확정 전): 신호 유형별 가중치. 양수 = 선호, 음수 = 비선호.
_SIGNAL_WEIGHTS: dict[str, float] = {
    "like": 1.0,
    "unlike": -1.0,
    "hide": -1.5,
    "report": -2.0,
}
# D2 잠정값: 신호 가중치가 절반이 되는 경과 일수.
_HALF_LIFE_DAYS = 14.0
# 행동 전용 신규 Topic의 confidence 기본·증가 계수.
_BEHAVIOR_BASE_CONFIDENCE = 0.35
_BEHAVIOR_CONFIDENCE_STEP = 0.05


def _decayed_weight(
    signal_type: str, occurred_at: object, *, now: datetime
) -> float:
    """신호 유형 가중치에 발생 시각 기준 시간 감쇠를 적용한다."""
    weight = _SIGNAL_WEIGHTS.get(signal_type, 0.0)
    if weight == 0.0:
        return 0.0
    if not isinstance(occurred_at, datetime):
        return weight
    moment = occurred_at if occurred_at.tzinfo else occurred_at.replace(tzinfo=UTC)
    age_days = max(0.0, (now - moment).total_seconds() / 86400.0)
    return weight * (0.5 ** (age_days / _HALF_LIFE_DAYS))


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def int_005(
    candidates: Sequence[InterestCandidate],
    *,
    signals: Sequence[Mapping[str, object]],
    now: datetime | None = None,
) -> list[InterestCandidate]:
    """[INT-005] 관심사 점수 계산.

    사용자 행동 강도와 최신성을 기반으로 점수를 계산한다. Wiki 반복도
    후보의 가중치에 행동 보정치를 더해 재정규화하고, Wiki에 없는 Topic에
    양의 신호가 쌓이면 행동 전용 후보로 추가한다.

    Args:
        candidates: INT-001이 계산한 Wiki 기반 관심 후보
        signals: Topic 단위 행동 신호 목록
            (`topic`·`signal_type`·`occurred_at` 키 사용)
        now: 감쇠 계산 기준 시각 (기본값: 현재 UTC)

    Returns:
        행동 보정이 반영되어 점수 내림차순으로 정렬된 후보 목록
    """
    reference = now or datetime.now(UTC)
    boosts: dict[str, float] = {}
    labels: dict[str, str] = {}
    behavior_reasons: dict[str, set[str]] = {}
    for signal in signals:
        topic = str(signal.get("topic") or "").strip()
        signal_type = str(signal.get("signal_type") or "").strip()
        if not topic or signal_type not in _SIGNAL_WEIGHTS:
            continue
        key = topic.casefold()
        labels.setdefault(key, topic)
        boosts[key] = boosts.get(key, 0.0) + _decayed_weight(
            signal_type, signal.get("occurred_at"), now=reference
        )
        behavior_reasons.setdefault(key, set()).add(f"behavior:{signal_type}")
    if not boosts:
        return list(candidates)

    adjusted: list[tuple[float, InterestCandidate]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.topic.casefold()
        seen.add(key)
        base_weight = float(candidate.evidence.get("weight", candidate.score) or 0.0)
        boost = boosts.get(key, 0.0)
        weight = max(0.0, base_weight + boost)
        evidence = dict(candidate.evidence)
        if key in boosts:
            existing_reasons = evidence.get("reasons")
            reasons = set(existing_reasons) if isinstance(existing_reasons, list) else set()
            evidence["reasons"] = sorted(reasons | behavior_reasons[key])
            evidence["behavior_boost"] = round(boost, 6)
        evidence["weight"] = weight
        confidence = candidate.confidence
        if boost > 0:
            confidence = min(0.99, confidence + _BEHAVIOR_CONFIDENCE_STEP)
        adjusted.append(
            (
                weight,
                InterestCandidate(
                    topic=candidate.topic,
                    category=candidate.category,
                    score=candidate.score,
                    confidence=round(confidence, 6),
                    document_ids=candidate.document_ids,
                    evidence=evidence,
                ),
            )
        )
    for key, boost in boosts.items():
        if key in seen or boost <= 0:
            continue
        adjusted.append(
            (
                boost,
                InterestCandidate(
                    topic=labels[key],
                    category=None,
                    score=0.0,
                    confidence=round(
                        min(
                            0.99,
                            _BEHAVIOR_BASE_CONFIDENCE
                            + min(boost, 10.0) * _BEHAVIOR_CONFIDENCE_STEP,
                        ),
                        6,
                    ),
                    document_ids=(),
                    evidence={
                        "weight": boost,
                        "behavior_boost": round(boost, 6),
                        "reasons": sorted(behavior_reasons[key]),
                    },
                ),
            )
        )

    max_weight = max((weight for weight, _ in adjusted), default=0.0)
    if max_weight <= 0:
        return [candidate for _, candidate in adjusted]
    rescored = [
        InterestCandidate(
            topic=candidate.topic,
            category=candidate.category,
            score=round(min(1.0, weight / max_weight), 6),
            confidence=candidate.confidence,
            document_ids=candidate.document_ids,
            evidence=candidate.evidence,
        )
        for weight, candidate in adjusted
    ]
    return sorted(
        rescored,
        key=lambda candidate: (-candidate.score, candidate.topic.casefold()),
    )


async def int_006(request: FeatureRequest) -> FeatureResult:
    """[INT-006] 관심사 Confidence 계산.

    추론된 관심사의 신뢰도를 계산한다.
    """
    raise NotImplementedError("[INT-006] 기능 구현이 필요합니다.")


async def int_008(request: FeatureRequest) -> FeatureResult:
    """[INT-008] 관심사 시간 감쇠.

    오래된 관심사의 가중치를 점진적으로 낮춘다.
    """
    raise NotImplementedError("[INT-008] 기능 구현이 필요합니다.")


async def int_009(request: FeatureRequest) -> FeatureResult:
    """[INT-009] 비선호 관심사 반영.

    숨김, 차단, 신고 등의 부정 신호를 반영한다.
    """
    raise NotImplementedError("[INT-009] 기능 구현이 필요합니다.")
