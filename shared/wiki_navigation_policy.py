"""리포트 유형별 LLM Wiki 탐색 프로필과 고정 실행 예산.

API 요청에서 선택한 프로필을 Worker 재시도까지 같은 값으로 유지하고,
Navigator가 깊이·Seed·Page·Chunk 상한을 한 계약으로 해석하게 한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_1HOP_PROFILE = "DEFAULT_1HOP"
ON_DEMAND_2HOP_PROFILE = "ON_DEMAND_2HOP"


@dataclass(frozen=True, slots=True)
class WikiNavigationBudget:
    """Navigator 한 번이 사용할 깊이·문서·Chunk 상한."""

    max_depth: int
    max_seed_pages: int
    max_pages: int
    max_chunks: int
    hop_page_limits: tuple[int, ...]

    def __post_init__(self) -> None:
        """운영 상한과 깊이별 할당이 서로 모순되지 않는지 검증한다."""
        if not 1 <= self.max_depth <= 2:
            raise ValueError("Wiki 탐색 깊이는 1 또는 2여야 합니다.")
        if not 1 <= self.max_pages <= 12:
            raise ValueError("Wiki 탐색 Page 수는 1에서 12 사이여야 합니다.")
        if not 1 <= self.max_seed_pages <= self.max_pages:
            raise ValueError("Wiki Seed Page 수는 전체 Page 상한 안이어야 합니다.")
        if not 1 <= self.max_chunks <= 12:
            raise ValueError("Wiki 탐색 Chunk 수는 1에서 12 사이여야 합니다.")
        if len(self.hop_page_limits) != self.max_depth:
            raise ValueError("깊이별 Page 할당 수는 Wiki 탐색 깊이와 같아야 합니다.")
        if any(limit < 0 for limit in self.hop_page_limits):
            raise ValueError("깊이별 Page 할당은 음수일 수 없습니다.")

    def to_payload(self) -> dict[str, object]:
        """Job·Snapshot에 저장할 JSON 호환 예산을 반환한다."""
        return {
            "max_depth": self.max_depth,
            "max_seed_pages": self.max_seed_pages,
            "max_pages": self.max_pages,
            "max_chunks": self.max_chunks,
            "hop_page_limits": list(self.hop_page_limits),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "WikiNavigationBudget":
        """Job에 고정된 JSON 예산을 검증된 값 객체로 복원한다."""
        raw_hop_limits = payload.get("hop_page_limits")
        if not isinstance(raw_hop_limits, (list, tuple)):
            raise ValueError("Wiki 탐색 예산에 hop_page_limits가 필요합니다.")
        try:
            return cls(
                max_depth=int(payload["max_depth"]),
                max_seed_pages=int(payload["max_seed_pages"]),
                max_pages=int(payload["max_pages"]),
                max_chunks=int(payload["max_chunks"]),
                hop_page_limits=tuple(int(value) for value in raw_hop_limits),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Wiki 탐색 예산 형식이 잘못됐습니다.") from error


@dataclass(frozen=True, slots=True)
class WikiNavigationPolicy:
    """이름과 실행 예산을 함께 고정한 Wiki 탐색 정책."""

    profile: str
    budget: WikiNavigationBudget


DEFAULT_WIKI_NAVIGATION_POLICY = WikiNavigationPolicy(
    profile=DEFAULT_1HOP_PROFILE,
    budget=WikiNavigationBudget(
        max_depth=1,
        max_seed_pages=6,
        max_pages=6,
        max_chunks=12,
        hop_page_limits=(6,),
    ),
)
ON_DEMAND_2HOP_WIKI_NAVIGATION_POLICY = WikiNavigationPolicy(
    profile=ON_DEMAND_2HOP_PROFILE,
    budget=WikiNavigationBudget(
        max_depth=2,
        max_seed_pages=2,
        max_pages=6,
        max_chunks=12,
        hop_page_limits=(2, 2),
    ),
)

_POLICIES = {
    DEFAULT_WIKI_NAVIGATION_POLICY.profile: DEFAULT_WIKI_NAVIGATION_POLICY,
    ON_DEMAND_2HOP_WIKI_NAVIGATION_POLICY.profile: (
        ON_DEMAND_2HOP_WIKI_NAVIGATION_POLICY
    ),
}


def resolve_wiki_navigation_policy(
    profile: str | None,
    *,
    pinned_budget: Mapping[str, object] | None = None,
) -> WikiNavigationPolicy:
    """프로필을 해석하고, 있으면 접수 시 고정한 예산을 우선 복원한다."""
    normalized = str(profile or DEFAULT_1HOP_PROFILE).strip()
    configured = _POLICIES.get(normalized)
    if configured is None:
        raise ValueError(f"지원하지 않는 Wiki 탐색 프로필입니다: {normalized}")
    budget = (
        WikiNavigationBudget.from_payload(pinned_budget)
        if pinned_budget is not None
        else configured.budget
    )
    return WikiNavigationPolicy(profile=configured.profile, budget=budget)
