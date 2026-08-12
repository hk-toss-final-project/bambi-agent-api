"""Personal Wiki V3 의미 감사의 결정적 입력과 후보를 구성한다.

현재 Wiki Page·관계와 활성 원본을 안정적인 참조로 고정하고, 전체 Page 쌍을
LLM에 전달하지 않도록 관련 항목 선언·공유 출처·어휘 유사도·공통 이웃 신호로
누락 관계 후보를 축소한다. 이 모듈의 후보 점수는 관계를 자동 생성하지 않는다.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from agent.wiki_builder.features.identity_resolution import normalize_wiki_surface
from agent.wiki_builder.features.relation_candidates import (
    RelationCandidateConfig,
    RelationCandidateQuery,
    WikiNodeIdentity,
    retrieve_wiki_relation_candidates,
)
from shared.wiki_models import ExistingWikiEntry, WikiRelationPlan


@dataclass(frozen=True, slots=True)
class WikiSemanticLintLimits:
    """의미 감사 입력과 전역 관계 후보의 결정적 상한."""

    page_limit: int = 80
    source_limit: int = 24
    source_chars: int = 2_400
    candidates_per_page: int = 4
    relation_candidate_limit: int = 40


@dataclass(frozen=True, slots=True)
class WikiSemanticSourceDocument:
    """의미 감사에 필요한 활성 원본 Version의 최소 입력."""

    source_document_version_id: str
    title: str
    raw_content: str
    source_type: str = "document"
    canonical_url: str | None = None
    published_at: datetime | None = None
    source_metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WikiSemanticPage:
    """LLM 의미 감사에서 안정적인 참조를 부여한 현재 Wiki Page."""

    reference: str
    document_kind: str
    document_key: str
    title: str
    summary: str
    aliases: tuple[str, ...]
    sources: tuple[str, ...]
    metadata: Mapping[str, object]

    @property
    def identity(self) -> WikiNodeIdentity:
        """Page의 canonical 종류·Key 식별자를 반환한다."""
        return WikiNodeIdentity(self.document_kind, self.document_key)


@dataclass(frozen=True, slots=True)
class WikiSemanticSource:
    """LLM 의미 감사에서 안정적인 참조와 제한된 본문을 가진 원본."""

    reference: str
    source_document_version_id: str
    title: str
    content: str
    source_type: str
    canonical_url: str | None
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class WikiGlobalRelationCandidate:
    """LLM이 검토할 기존 두 Page 사이의 누락 관계 후보."""

    reference: str
    source_page_reference: str
    target_page_reference: str
    score: float
    signals: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WikiSemanticLintContext:
    """한 번의 V3 의미 감사에 고정된 Page·Source·관계 후보 입력."""

    pages: tuple[WikiSemanticPage, ...]
    sources: tuple[WikiSemanticSource, ...]
    relations: tuple[WikiRelationPlan, ...]
    relation_candidates: tuple[WikiGlobalRelationCandidate, ...]


@dataclass(slots=True)
class _RelationCandidateAccumulator:
    """동일한 Page 쌍에 들어온 후보 신호와 최고 점수를 누적한다."""

    source_page_reference: str
    target_page_reference: str
    score: float = 0.0
    signals: set[str] = field(default_factory=set)


def _metadata_strings(metadata: Mapping[str, object], key: str) -> tuple[str, ...]:
    """Metadata 배열에서 비어 있지 않은 문자열만 읽는다."""
    value = metadata.get(key)
    if not isinstance(value, (list, tuple, set, frozenset)):
        return ()
    return tuple(item for raw in value if (item := str(raw).strip()))


def _validate_limits(limits: WikiSemanticLintLimits) -> None:
    """의미 감사 상한이 음수가 아닌지 검증한다."""
    for name, value in (
        ("page_limit", limits.page_limit),
        ("source_limit", limits.source_limit),
        ("source_chars", limits.source_chars),
        ("candidates_per_page", limits.candidates_per_page),
        ("relation_candidate_limit", limits.relation_candidate_limit),
    ):
        if value < 0:
            raise ValueError(f"{name}은 0 이상이어야 합니다.")


def _build_pages(
    entries: Sequence[ExistingWikiEntry],
    *,
    limit: int,
) -> tuple[WikiSemanticPage, ...]:
    """현재 Wiki Page를 canonical 순서로 제한하고 안정적인 참조를 붙인다."""
    selected = sorted(
        (
            entry
            for entry in entries
            if entry.document_kind in {"entity", "concept"}
        ),
        key=lambda entry: (entry.document_kind, entry.document_key),
    )[:limit]
    return tuple(
        WikiSemanticPage(
            reference=f"P{index}",
            document_kind=entry.document_kind,
            document_key=entry.document_key,
            title=entry.title,
            summary=str(entry.summary or ""),
            aliases=_metadata_strings(entry.metadata, "aliases"),
            sources=_metadata_strings(entry.metadata, "sources"),
            metadata=dict(entry.metadata),
        )
        for index, entry in enumerate(selected, start=1)
    )


def _build_sources(
    sources: Sequence[WikiSemanticSourceDocument],
    *,
    limit: int,
    content_limit: int,
) -> tuple[WikiSemanticSource, ...]:
    """활성 원본을 안정적인 순서와 본문 길이 상한으로 고정한다."""
    selected = sorted(
        sources,
        key=lambda source: (
            source.source_type != "onboarding_seed",
            source.source_document_version_id,
        ),
    )[:limit]
    return tuple(
        WikiSemanticSource(
            reference=f"S{index}",
            source_document_version_id=source.source_document_version_id,
            title=source.title,
            content=source.raw_content[:content_limit],
            source_type=source.source_type,
            canonical_url=source.canonical_url,
            published_at=source.published_at,
        )
        for index, source in enumerate(selected, start=1)
    )


def _identity_pair(
    left: WikiNodeIdentity,
    right: WikiNodeIdentity,
) -> tuple[WikiNodeIdentity, WikiNodeIdentity]:
    """방향과 무관하게 같은 두 Page를 나타내는 정렬된 식별자 쌍을 만든다."""
    return (left, right) if left <= right else (right, left)


def _existing_pairs(
    relations: Sequence[WikiRelationPlan],
) -> set[tuple[WikiNodeIdentity, WikiNodeIdentity]]:
    """현재 관계가 이미 연결한 endpoint 쌍을 방향과 유형에 무관하게 모은다."""
    return {
        _identity_pair(
            WikiNodeIdentity(
                relation.source_document_kind,
                relation.source_document_key,
            ),
            WikiNodeIdentity(
                relation.target_document_kind,
                relation.target_document_key,
            ),
        )
        for relation in relations
    }


def _surface_index(
    pages: Sequence[WikiSemanticPage],
) -> dict[str, tuple[WikiSemanticPage, ...]]:
    """Page 제목과 별칭의 정규화 표면형을 Page 목록으로 색인한다."""
    indexed: defaultdict[str, list[WikiSemanticPage]] = defaultdict(list)
    for page in pages:
        for surface in (page.title, *page.aliases):
            marker = normalize_wiki_surface(surface)
            if marker and page not in indexed[marker]:
                indexed[marker].append(page)
    return {key: tuple(value) for key, value in indexed.items()}


def _candidate_key(
    source: WikiSemanticPage,
    target: WikiSemanticPage,
) -> tuple[str, str]:
    """같은 Page 쌍을 한 번만 누적하도록 참조를 정렬한다."""
    return (
        (source.reference, target.reference)
        if source.reference < target.reference
        else (target.reference, source.reference)
    )


def _add_candidate(
    accumulators: dict[tuple[str, str], _RelationCandidateAccumulator],
    source: WikiSemanticPage,
    target: WikiSemanticPage,
    *,
    score: float,
    signal: str,
    existing_pairs: set[tuple[WikiNodeIdentity, WikiNodeIdentity]],
) -> None:
    """자기 관계와 기존 연결을 제외하고 Page 쌍 후보 신호를 누적한다."""
    if source.identity == target.identity:
        return
    if _identity_pair(source.identity, target.identity) in existing_pairs:
        return
    source_ref, target_ref = _candidate_key(source, target)
    accumulator = accumulators.setdefault(
        (source_ref, target_ref),
        _RelationCandidateAccumulator(source_ref, target_ref),
    )
    accumulator.score = max(accumulator.score, max(0.0, min(1.0, score)))
    accumulator.signals.add(signal)


def _add_declared_link_candidates(
    accumulators: dict[tuple[str, str], _RelationCandidateAccumulator],
    pages: Sequence[WikiSemanticPage],
    *,
    existing_pairs: set[tuple[WikiNodeIdentity, WikiNodeIdentity]],
) -> None:
    """Metadata 관련 항목이 가리키지만 Edge가 없는 Page 쌍을 후보로 만든다."""
    surface_index = _surface_index(pages)
    for page in pages:
        declared = (
            *_metadata_strings(page.metadata, "related_entities"),
            *_metadata_strings(page.metadata, "related_concepts"),
        )
        for label in declared:
            for target in surface_index.get(normalize_wiki_surface(label), ()):
                _add_candidate(
                    accumulators,
                    page,
                    target,
                    score=0.95,
                    signal="declared_related_page",
                    existing_pairs=existing_pairs,
                )


def _add_shared_source_candidates(
    accumulators: dict[tuple[str, str], _RelationCandidateAccumulator],
    pages: Sequence[WikiSemanticPage],
    *,
    existing_pairs: set[tuple[WikiNodeIdentity, WikiNodeIdentity]],
) -> None:
    """같은 원본에서 근거를 얻었지만 연결되지 않은 Page 쌍을 후보로 만든다."""
    for index, source in enumerate(pages):
        source_links = set(source.sources)
        if not source_links:
            continue
        for target in pages[index + 1 :]:
            overlap = source_links & set(target.sources)
            if not overlap:
                continue
            _add_candidate(
                accumulators,
                source,
                target,
                score=min(0.72, 0.48 + 0.08 * len(overlap)),
                signal=f"shared_source:{len(overlap)}",
                existing_pairs=existing_pairs,
            )


def _add_lexical_candidates(
    accumulators: dict[tuple[str, str], _RelationCandidateAccumulator],
    pages: Sequence[WikiSemanticPage],
    *,
    per_page_limit: int,
    existing_pairs: set[tuple[WikiNodeIdentity, WikiNodeIdentity]],
) -> None:
    """기존 후보 회수기의 어휘·trigram 신호로 Page별 상위 후보를 추가한다."""
    entries = [
        ExistingWikiEntry(
            document_kind=page.document_kind,
            document_key=page.document_key,
            title=page.title,
            domain=str(page.metadata.get("subtype") or "") or None,
            summary=page.summary,
            metadata=dict(page.metadata),
        )
        for page in pages
    ]
    page_by_identity = {page.identity: page for page in pages}
    config = RelationCandidateConfig(
        limit=per_page_limit,
        graph_seed_limit=0,
        minimum_lexical_score=0.25,
        minimum_trigram_score=0.2,
    )
    for page in pages:
        candidates = retrieve_wiki_relation_candidates(
            RelationCandidateQuery(
                label=page.title,
                aliases=page.aliases,
                context=page.summary,
                matched_existing_identity=page.identity,
            ),
            entries,
            config=config,
        )
        for candidate in candidates:
            target = page_by_identity.get(candidate.identity)
            if target is None:
                continue
            signal_names = "+".join(
                sorted({signal.kind for signal in candidate.signals})
            )
            _add_candidate(
                accumulators,
                page,
                target,
                score=candidate.score,
                signal=f"lexical:{signal_names}",
                existing_pairs=existing_pairs,
            )


def _add_common_neighbor_candidates(
    accumulators: dict[tuple[str, str], _RelationCandidateAccumulator],
    pages: Sequence[WikiSemanticPage],
    relations: Sequence[WikiRelationPlan],
    *,
    existing_pairs: set[tuple[WikiNodeIdentity, WikiNodeIdentity]],
) -> None:
    """검증 Graph에서 공통 이웃을 가진 미연결 Page 쌍을 후보로 만든다."""
    adjacency: defaultdict[WikiNodeIdentity, set[WikiNodeIdentity]] = defaultdict(set)
    for relation in relations:
        source = WikiNodeIdentity(
            relation.source_document_kind,
            relation.source_document_key,
        )
        target = WikiNodeIdentity(
            relation.target_document_kind,
            relation.target_document_key,
        )
        adjacency[source].add(target)
        adjacency[target].add(source)
    for index, source in enumerate(pages):
        for target in pages[index + 1 :]:
            common = adjacency[source.identity] & adjacency[target.identity]
            if not common:
                continue
            _add_candidate(
                accumulators,
                source,
                target,
                score=min(0.78, 0.52 + 0.08 * len(common)),
                signal=f"common_neighbor:{len(common)}",
                existing_pairs=existing_pairs,
            )


def build_global_relation_candidates(
    pages: Sequence[WikiSemanticPage],
    relations: Sequence[WikiRelationPlan],
    *,
    per_page_limit: int = 4,
    limit: int = 40,
) -> tuple[WikiGlobalRelationCandidate, ...]:
    """현재 Wiki 전체에서 LLM이 검토할 누락 관계 후보를 결정적으로 만든다."""
    if per_page_limit <= 0 or limit <= 0 or len(pages) < 2:
        return ()
    existing_pairs = _existing_pairs(relations)
    accumulators: dict[tuple[str, str], _RelationCandidateAccumulator] = {}
    _add_declared_link_candidates(
        accumulators,
        pages,
        existing_pairs=existing_pairs,
    )
    _add_shared_source_candidates(
        accumulators,
        pages,
        existing_pairs=existing_pairs,
    )
    _add_lexical_candidates(
        accumulators,
        pages,
        per_page_limit=per_page_limit,
        existing_pairs=existing_pairs,
    )
    _add_common_neighbor_candidates(
        accumulators,
        pages,
        relations,
        existing_pairs=existing_pairs,
    )
    ranked = sorted(
        accumulators.values(),
        key=lambda candidate: (
            -candidate.score,
            -len(candidate.signals),
            candidate.source_page_reference,
            candidate.target_page_reference,
        ),
    )[:limit]
    return tuple(
        WikiGlobalRelationCandidate(
            reference=f"C{index}",
            source_page_reference=candidate.source_page_reference,
            target_page_reference=candidate.target_page_reference,
            score=candidate.score,
            signals=tuple(sorted(candidate.signals)),
        )
        for index, candidate in enumerate(ranked, start=1)
    )


def build_wiki_semantic_lint_context(
    entries: Sequence[ExistingWikiEntry],
    relations: Sequence[WikiRelationPlan],
    sources: Sequence[WikiSemanticSourceDocument],
    *,
    limits: WikiSemanticLintLimits = WikiSemanticLintLimits(),
) -> WikiSemanticLintContext:
    """현재 Wiki와 활성 원본을 제한된 V3 의미 감사 입력으로 변환한다."""
    _validate_limits(limits)
    pages = _build_pages(entries, limit=limits.page_limit)
    semantic_sources = _build_sources(
        sources,
        limit=limits.source_limit,
        content_limit=limits.source_chars,
    )
    page_identities = {page.identity for page in pages}
    selected_relations = tuple(
        relation
        for relation in relations
        if WikiNodeIdentity(
            relation.source_document_kind,
            relation.source_document_key,
        )
        in page_identities
        and WikiNodeIdentity(
            relation.target_document_kind,
            relation.target_document_key,
        )
        in page_identities
    )
    candidates = build_global_relation_candidates(
        pages,
        selected_relations,
        per_page_limit=limits.candidates_per_page,
        limit=limits.relation_candidate_limit,
    )
    return WikiSemanticLintContext(
        pages=pages,
        sources=semantic_sources,
        relations=selected_relations,
        relation_candidates=candidates,
    )


def page_by_reference(
    context: WikiSemanticLintContext,
) -> dict[str, WikiSemanticPage]:
    """의미 감사 Page를 안정적인 참조로 찾는 Map을 만든다."""
    return {page.reference: page for page in context.pages}


def source_by_reference(
    context: WikiSemanticLintContext,
) -> dict[str, WikiSemanticSource]:
    """의미 감사 원본을 안정적인 참조로 찾는 Map을 만든다."""
    return {source.reference: source for source in context.sources}


def candidate_by_reference(
    context: WikiSemanticLintContext,
) -> dict[str, WikiGlobalRelationCandidate]:
    """누락 관계 후보를 안정적인 참조로 찾는 Map을 만든다."""
    return {
        candidate.reference: candidate for candidate in context.relation_candidates
    }


def iter_context_surfaces(context: WikiSemanticLintContext) -> Iterable[str]:
    """현재 Page의 제목과 별칭을 누락 주제 중복 검사 순서로 반환한다."""
    for page in context.pages:
        yield page.title
        yield from page.aliases


__all__ = [
    "WikiGlobalRelationCandidate",
    "WikiSemanticLintContext",
    "WikiSemanticLintLimits",
    "WikiSemanticPage",
    "WikiSemanticSource",
    "WikiSemanticSourceDocument",
    "build_global_relation_candidates",
    "build_wiki_semantic_lint_context",
    "candidate_by_reference",
    "iter_context_surfaces",
    "page_by_reference",
    "source_by_reference",
]
