"""관심사 점수 계산 기능 구현.

INT-005의 실제 구현 위치다. INT-001이 만든 Wiki 구조 기반 후보에 사용자 행동
강도(근거 원문의 수와 종류)와 최신성 감쇠를 곱해 최종 관심도 점수를 계산한다.
INT-006, INT-008, INT-009 기능의 구현 위치도 이 모듈이 소유한다.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime

from shared.contracts import FeatureRequest, FeatureResult
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
}
# 근거 원문 시각을 알 수 없을 때 최신성으로 유리하지도 불리하지도 않게 두는 값.
_NEUTRAL_RECENCY = 0.5
_DEFAULT_HALF_LIFE_DAYS = 90.0


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
    volume = math.log1p(float(source_count)) if isinstance(source_count, (int, float)) else 0.0
    return 1.0 + type_bonus + volume * 0.5


def _structure_weight(candidate: InterestCandidate) -> float:
    """INT-001이 계산한 Wiki 구조 가중치를 읽는다."""
    weight = candidate.evidence.get("structure_weight")
    if isinstance(weight, (int, float)) and weight > 0:
        return float(weight)
    return max(candidate.score, 0.0) or 1.0


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def int_005(
    candidates: Sequence[InterestCandidate],
    *,
    reference_time: datetime | None = None,
    limit: int = 20,
    half_life_days: float = _DEFAULT_HALF_LIFE_DAYS,
) -> list[InterestCandidate]:
    """[INT-005] 관심사 점수 계산.

    사용자 행동 강도와 최신성을 기반으로 점수를 계산한다. INT-001의 Wiki
    구조 가중치에 근거 원문 강도와 반감기 감쇠를 곱한 뒤, 최고 점수를 1.0으로
    정규화하고 점수 내림차순으로 다시 정렬한다.

    Args:
        candidates: INT-001이 추출한 관심 후보 목록
        reference_time: 최신성 기준 시각 (생략하면 현재 UTC)
        limit: 반환할 최대 관심 후보 수 (1~100)
        half_life_days: 관심도가 절반으로 줄어드는 기간(일)

    Returns:
        최종 점수 내림차순으로 정렬된 관심 후보 목록
    """
    if not 1 <= limit <= 100:
        raise ValueError("관심 후보 limit은 1에서 100 사이여야 합니다.")
    if half_life_days <= 0:
        raise ValueError("관심사 반감기는 0보다 커야 합니다.")
    if not candidates:
        return []

    now = _as_aware(reference_time) if reference_time else datetime.now(UTC)
    raw_scores: list[float] = []
    factors: list[tuple[float, float]] = []
    for candidate in candidates:
        intensity = _intensity(candidate.evidence)
        recency = _recency(
            candidate.evidence, reference_time=now, half_life_days=half_life_days
        )
        factors.append((intensity, recency))
        raw_scores.append(_structure_weight(candidate) * intensity * recency)

    max_raw = max(raw_scores)
    scored: list[InterestCandidate] = []
    for candidate, (intensity, recency), raw in zip(
        candidates, factors, raw_scores, strict=True
    ):
        score = min(1.0, raw / max_raw) if max_raw > 0 else 0.0
        scored.append(
            replace(
                candidate,
                score=round(score, 6),
                evidence={
                    **candidate.evidence,
                    "weight": round(raw, 6),
                    "behavior_intensity": round(intensity, 6),
                    "recency_factor": round(recency, 6),
                    "half_life_days": half_life_days,
                    "scored_at": now.isoformat(),
                },
            )
        )
    scored.sort(
        key=lambda candidate: (
            -candidate.score,
            -len(candidate.document_ids),
            candidate.topic.casefold(),
        )
    )
    return scored[:limit]


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
