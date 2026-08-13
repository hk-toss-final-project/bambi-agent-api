"""관심사 점수 계산 기능 구현.

INT-005의 실제 구현 위치다. 점수는 두 층으로 계산한다.

1. 기본 점수 — INT-001의 Wiki 구조 가중치에 근거 원문의 수·종류(행동 강도)와
   최신 활동 시각 기반 반감기 감쇠를 곱한다.
2. 행동 보정 — 좋아요·숨김 같은 사용자 행동 신호에 시간 감쇠를 적용해 기본
   점수에 더한다. Wiki에 없는 Topic도 양의 신호가 쌓이면 후보로 추가한다.

두 층을 합산한 뒤 최고 점수를 1.0으로 재정규화한다. LLM 없이 결정적으로
계산하며, 행동 신호 가중치와 신호 반감기는 팀 확정 전 잠정값(D2)이다.
INT-006, INT-008, INT-009 기능의 구현 위치도 이 모듈이 소유한다.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime

from shared.wiki_models import InterestCandidate

# 사용자가 원문에 직접 개입한 정도가 클수록 큰 가중치를 준다.
_SOURCE_TYPE_WEIGHTS = {
    "memo": 0.6,
    "edit": 0.6,
    "conversation": 0.4,
    "content_mark": 0.35,
    "content_save": 0.3,
    "web_clipping": 0.2,
    "url": 0.15,
    # 온보딩 시드는 실제 저장 근거가 아니라 콜드스타트용 출발점이라 가장 낮게 둔다.
    # 이후 클리핑·저장(0.2 이상)이 쌓이면 재계산 시 자연히 상위로 밀려난다.
    "onboarding_seed": 0.15,
}
# 근거 원문 시각을 알 수 없을 때 최신성으로 유리하지도 불리하지도 않게 두는 값.
_NEUTRAL_RECENCY = 0.5
_DEFAULT_HALF_LIFE_DAYS = 90.0

# D2 잠정값(팀 확정 전): 신호 유형별 가중치. 양수 = 선호, 음수 = 비선호.
_SIGNAL_WEIGHTS: dict[str, float] = {
    "like": 1.0,
    "unlike": -1.0,
    "hide": -1.5,
    "report": -2.0,
}
# D2 잠정값: 행동 신호 가중치가 절반이 되는 경과 일수(Wiki 최신성 반감기와 별개).
_SIGNAL_HALF_LIFE_DAYS = 14.0
# 행동 전용 신규 Topic의 confidence 기본·증가 계수.
_BEHAVIOR_BASE_CONFIDENCE = 0.35
_BEHAVIOR_CONFIDENCE_STEP = 0.05


def _as_aware(value: datetime) -> datetime:
    """Timezone이 없는 시각을 UTC 기준으로 맞춘다."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _last_activity(evidence: dict[str, object]) -> datetime | None:
    """근거에 기록된 최신 활동 시각을 datetime으로 되돌린다."""
    raw = evidence.get("last_activity_at")
    if isinstance(raw, datetime):
        return _as_aware(raw)
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return _as_aware(datetime.fromisoformat(raw))
    except ValueError:
        return None


def _recency(
    evidence: dict[str, object], *, reference_time: datetime, half_life_days: float
) -> float:
    """최신 활동 시각으로부터 경과한 기간을 반감기 감쇠 계수로 변환한다."""
    last_activity = _last_activity(evidence)
    if last_activity is None:
        return _NEUTRAL_RECENCY
    elapsed_days = (reference_time - last_activity).total_seconds() / 86400
    if elapsed_days <= 0:
        return 1.0
    return 0.5 ** (elapsed_days / half_life_days)


def _intensity(evidence: dict[str, object]) -> float:
    """근거 원문의 종류와 개수를 사용자 행동 강도 가중치로 변환한다."""
    source_types = evidence.get("source_types")
    type_bonus = 0.0
    if isinstance(source_types, (list, tuple)):
        type_bonus = sum(
            _SOURCE_TYPE_WEIGHTS.get(str(source_type), 0.1)
            for source_type in {str(item) for item in source_types}
        )
    source_count = evidence.get("source_count")
    volume = (
        math.log1p(float(source_count))
        if isinstance(source_count, (int, float))
        else 0.0
    )
    return 1.0 + type_bonus + volume * 0.5


def _structure_weight(candidate: InterestCandidate) -> float:
    """INT-001이 계산한 Wiki 구조 가중치를 읽는다.

    structure_weight가 없으면 이전 단계가 남긴 weight를, 그것도 없으면
    후보 점수를 기본 가중치로 사용한다.
    """
    for key in ("structure_weight", "weight"):
        value = candidate.evidence.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return max(candidate.score, 0.0) or 1.0


def _decayed_weight(signal_type: str, occurred_at: object, *, now: datetime) -> float:
    """신호 유형 가중치에 발생 시각 기준 시간 감쇠를 적용한다."""
    weight = _SIGNAL_WEIGHTS.get(signal_type, 0.0)
    if weight == 0.0:
        return 0.0
    if not isinstance(occurred_at, datetime):
        return weight
    moment = _as_aware(occurred_at)
    age_days = max(0.0, (now - moment).total_seconds() / 86400.0)
    return weight * (0.5 ** (age_days / _SIGNAL_HALF_LIFE_DAYS))


def _collect_signal_boosts(
    signals: Sequence[Mapping[str, object]], *, now: datetime
) -> tuple[dict[str, float], dict[str, str], dict[str, set[str]]]:
    """Topic 단위 행동 신호를 감쇠 합산한 보정치로 정리한다."""
    boosts: dict[str, float] = {}
    labels: dict[str, str] = {}
    reasons: dict[str, set[str]] = {}
    for signal in signals:
        topic = str(signal.get("topic") or "").strip()
        signal_type = str(signal.get("signal_type") or "").strip()
        if not topic or signal_type not in _SIGNAL_WEIGHTS:
            continue
        key = topic.casefold()
        labels.setdefault(key, topic)
        boosts[key] = boosts.get(key, 0.0) + _decayed_weight(
            signal_type, signal.get("occurred_at"), now=now
        )
        reasons.setdefault(key, set()).add(f"behavior:{signal_type}")
    return boosts, labels, reasons


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def int_005(
    candidates: Sequence[InterestCandidate],
    *,
    signals: Sequence[Mapping[str, object]] = (),
    now: datetime | None = None,
    limit: int = 20,
    half_life_days: float = _DEFAULT_HALF_LIFE_DAYS,
) -> list[InterestCandidate]:
    """[INT-005] 관심사 점수 계산.

    사용자 행동 강도와 최신성을 기반으로 점수를 계산한다. Wiki 구조 가중치에
    근거 원문 강도와 반감기 감쇠를 곱해 기본 점수를 만들고, 행동 신호 보정을
    더한 뒤 최고 점수를 1.0으로 재정규화한다.

    Args:
        candidates: INT-001이 추출한 관심 후보 목록
        signals: Topic 단위 행동 신호 목록
            (`topic`·`signal_type`·`occurred_at` 키 사용). 비어 있으면 기본
            점수만 계산한다.
        now: 감쇠 계산 기준 시각 (생략하면 현재 UTC)
        limit: 반환할 최대 관심 후보 수 (1~100)
        half_life_days: Wiki 최신성이 절반으로 줄어드는 기간(일)

    Returns:
        최종 점수 내림차순으로 정렬된 관심 후보 목록
    """
    if not 1 <= limit <= 100:
        raise ValueError("관심 후보 limit은 1에서 100 사이여야 합니다.")
    if half_life_days <= 0:
        raise ValueError("관심사 반감기는 0보다 커야 합니다.")

    reference = _as_aware(now) if now else datetime.now(UTC)
    boosts, labels, behavior_reasons = _collect_signal_boosts(signals, now=reference)
    if not candidates and not boosts:
        return []

    weighted: list[tuple[float, InterestCandidate]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.topic.casefold()
        seen.add(key)
        intensity = _intensity(candidate.evidence)
        recency = _recency(
            candidate.evidence, reference_time=reference, half_life_days=half_life_days
        )
        base = _structure_weight(candidate) * intensity * recency
        boost = boosts.get(key, 0.0)
        weight = max(0.0, base + boost)
        evidence: dict[str, object] = {
            **candidate.evidence,
            "weight": round(weight, 6),
            "base_weight": round(base, 6),
            "behavior_intensity": round(intensity, 6),
            "recency_factor": round(recency, 6),
            "half_life_days": half_life_days,
            "scored_at": reference.isoformat(),
        }
        confidence = candidate.confidence
        if key in boosts:
            existing = evidence.get("reasons")
            merged = set(existing) if isinstance(existing, list) else set()
            evidence["reasons"] = sorted(merged | behavior_reasons[key])
            evidence["behavior_boost"] = round(boost, 6)
            if boost > 0:
                confidence = min(0.99, confidence + _BEHAVIOR_CONFIDENCE_STEP)
        weighted.append(
            (
                weight,
                replace(candidate, confidence=round(confidence, 6), evidence=evidence),
            )
        )

    # Wiki에 없지만 양의 행동 신호가 쌓인 Topic은 행동 전용 후보로 추가한다.
    for key, boost in boosts.items():
        if key in seen or boost <= 0:
            continue
        weighted.append(
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
                        "weight": round(boost, 6),
                        "base_weight": 0.0,
                        "behavior_boost": round(boost, 6),
                        "reasons": sorted(behavior_reasons[key]),
                        "scored_at": reference.isoformat(),
                    },
                ),
            )
        )

    max_weight = max((weight for weight, _ in weighted), default=0.0)
    scored = [
        replace(
            candidate,
            score=round(min(1.0, weight / max_weight), 6) if max_weight > 0 else 0.0,
        )
        for weight, candidate in weighted
    ]
    scored.sort(
        key=lambda candidate: (
            -candidate.score,
            -len(candidate.document_ids),
            candidate.topic.casefold(),
        )
    )
    return scored[:limit]
