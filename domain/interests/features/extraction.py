"""개인 Wiki Entity·Concept 노드에서 관심 후보를 추출하는 기능 구현.

INT-001의 실제 구현 위치다. LLM 호출 없이 현재 Wiki의 Entity·Concept 노드와
연결 관계(degree)만으로 결정적인 관심 후보를 만든다. 노드 제목은 Wiki Builder가
이미 정제한 개념 이름이므로 토큰으로 다시 쪼개지 않는다. 최신성과 사용자 행동
강도를 반영한 최종 점수는 INT-005가 계산한다.

온보딩 시드(WSE-014)가 유일한 근거인 노드는 사용자가 고른 라벨과 맞을 때만
후보로 인정한다. 시드 문서에서 파생된 상위 묶음 노드가 관심사 1위를 차지하는
것을 막기 위해서다.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from shared.wiki_models import InterestCandidate

_GENERIC_DOMAINS = {"other"}
_ONBOARDING_SEED_SOURCE_TYPE = "onboarding_seed"


@dataclass(slots=True)
class _NodeGroup:
    """제목이 같은 Wiki 노드들을 하나의 관심 후보로 모으는 누적기."""

    topic: str
    category: str | None
    degree: float = 0.0
    source_count: int = 0
    document_ids: set[str] = field(default_factory=set)
    document_kinds: set[str] = field(default_factory=set)
    aliases: set[str] = field(default_factory=set)
    source_types: set[str] = field(default_factory=set)
    last_activity_at: str | None = None

    def absorb(self, node: Mapping[str, object]) -> None:
        """같은 제목을 가진 노드 하나의 신호를 누적한다."""
        document_kind = str(node.get("document_kind") or "")
        domain = str(node.get("domain") or "").strip() or None
        self.degree += float(node.get("degree") or 0.0)
        self.source_count += int(node.get("source_count") or 0)
        self.document_ids.add(str(node.get("document_id")))
        if document_kind:
            self.document_kinds.add(document_kind)
        self.aliases.update(_aliases(node.get("source_metadata")))
        self.source_types.update(_source_types(node.get("source_types")))
        if self.category is None and domain not in _GENERIC_DOMAINS:
            self.category = domain
        activity = _isoformat(node.get("last_activity_at"))
        if activity is not None and (
            self.last_activity_at is None or self.last_activity_at < activity
        ):
            self.last_activity_at = activity

    @property
    def structure_weight(self) -> float:
        """연결 수를 완만하게 증가하는 Wiki 구조 가중치로 변환한다.

        연결이 없는 노드도 후보로 남기기 위해 기본값 1.0에서 시작하고, 연결이
        많아질수록 증가폭이 줄도록 로그를 사용한다.
        """
        return 1.0 + math.log1p(max(self.degree, 0.0))


def _aliases(metadata: object) -> list[str]:
    """노드 Metadata에서 표기가 다른 별칭 목록을 정제해 반환한다."""
    if not isinstance(metadata, Mapping):
        return []
    values = metadata.get("aliases")
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        alias = str(value).strip()
        marker = alias.casefold()
        if alias and marker not in seen:
            seen.add(marker)
            result.append(alias)
    return result


def _source_types(value: object) -> list[str]:
    """근거 원문 종류 목록을 중복 없이 정렬해 반환한다."""
    if not isinstance(value, (list, tuple)):
        return []
    return sorted({str(item).strip() for item in value if str(item).strip()})


def _matches_onboarding_label(names: Iterable[str], labels: Sequence[str]) -> bool:
    """노드 이름·별칭 중 하나가 온보딩에서 고른 라벨과 맞는지 확인한다.

    Wiki Builder가 라벨을 그대로 쓰지 않고 조금 늘여 쓸 수 있으므로
    (`금리` → `기준금리`) 대소문자를 무시한 양방향 부분 일치로 본다.
    """
    for name in names:
        marker = name.casefold().strip()
        if not marker:
            continue
        for label in labels:
            token = label.casefold().strip()
            if token and (token in marker or marker in token):
                return True
    return False


def _is_unselected_seed_node(
    node: Mapping[str, object], labels: Sequence[str]
) -> bool:
    """온보딩 시드에서만 나왔고 사용자가 고르지 않은 노드인지 판정한다.

    시드 Markdown을 Wiki Builder에 태우면 사용자가 고른 주제 노드와 함께 그것들을
    묶는 상위 개념 노드("온보딩 관심 주제")가 생긴다. 이 묶음 노드는 연결 수가
    가장 많아 관심사 1위를 차지하지만 사용자가 선언한 관심사가 아니다. 시드가
    유일한 근거인 노드는 온보딩 라벨과 맞을 때만 관심 후보로 인정한다.

    실제 저장(클리핑·메모 등)이 같은 노드에 쌓이면 근거 종류가 늘어 이 판정에서
    빠지므로, 나중에 사용자가 그 주제를 실제로 저장하면 관심사로 되살아난다.
    """
    if not labels:
        return False
    source_types = set(_source_types(node.get("source_types")))
    if source_types != {_ONBOARDING_SEED_SOURCE_TYPE}:
        return False
    names = [str(node.get("title") or ""), *_aliases(node.get("source_metadata"))]
    return not _matches_onboarding_label(names, labels)


def _isoformat(value: object) -> str | None:
    """근거 원문의 최신 활동 시각을 JSON 저장용 ISO 문자열로 변환한다.

    저장소는 datetime을 넘기지만, 이미 ISO 문자열로 정규화된 입력도 그대로
    받아들인다. 형식을 알 수 없는 값은 최신성 계산에서 제외되도록 버린다.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value).isoformat()
    except ValueError:
        return None


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def int_001(
    documents: Sequence[Mapping[str, object]],
    *,
    limit: int = 20,
    onboarding_seed_labels: Sequence[str] = (),
) -> list[InterestCandidate]:
    """[INT-001] 관심사 Topic 추출.

    개인 Wiki의 Entity·Concept 노드를 관심 후보로 삼고 연결 수 기준으로
    정렬한다. 같은 제목의 노드는 하나의 후보로 합치고, 최신성·행동 강도
    반영에 필요한 신호는 근거(evidence)에 담아 INT-005로 넘긴다.

    Args:
        documents: 활성 Wiki의 Entity·Concept 노드 Row 목록
        limit: 반환할 최대 관심 후보 수 (1~100)
        onboarding_seed_labels: 온보딩에서 고른 관심 라벨 목록(WSE-014 시드).
            주어지면 시드가 유일한 근거인 노드 중 이 라벨과 맞지 않는 노드를
            후보에서 제외한다. 비어 있으면 종전대로 모든 노드를 후보로 둔다.

    Returns:
        Wiki 구조 점수 내림차순으로 정렬된 관심 후보 목록
    """
    if not 1 <= limit <= 100:
        raise ValueError("관심 후보 limit은 1에서 100 사이여야 합니다.")

    labels = [str(label) for label in onboarding_seed_labels if str(label).strip()]
    groups: dict[str, _NodeGroup] = {}
    for node in documents:
        document_id = str(node.get("document_id") or "")
        title = str(node.get("title") or "").strip()
        if not document_id or not title:
            continue
        if _is_unselected_seed_node(node, labels):
            continue
        key = title.casefold()
        if key not in groups:
            domain = str(node.get("domain") or "").strip() or None
            groups[key] = _NodeGroup(
                topic=title,
                category=domain if domain not in _GENERIC_DOMAINS else None,
            )
        groups[key].absorb(node)

    if not groups:
        return []

    max_weight = max(group.structure_weight for group in groups.values())
    ordered = sorted(
        groups.values(),
        key=lambda group: (
            -group.structure_weight,
            -len(group.document_ids),
            group.topic.casefold(),
        ),
    )[:limit]

    return [
        InterestCandidate(
            topic=group.topic,
            category=group.category,
            score=round(min(1.0, group.structure_weight / max_weight), 6),
            confidence=round(
                min(
                    0.99,
                    0.4 + group.source_count * 0.12 + min(group.degree, 10.0) * 0.03,
                ),
                6,
            ),
            document_ids=tuple(sorted(group.document_ids)),
            evidence={
                "weight": round(group.structure_weight, 6),
                "structure_weight": round(group.structure_weight, 6),
                "degree": group.degree,
                "source_count": group.source_count,
                "source_types": sorted(group.source_types),
                "aliases": sorted(group.aliases),
                "document_kinds": sorted(group.document_kinds),
                "last_activity_at": group.last_activity_at,
                "reasons": ["wiki_node"],
            },
        )
        for group in ordered
    ]
