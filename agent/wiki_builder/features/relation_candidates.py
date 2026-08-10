"""개인 Wiki 관계 판정에 사용할 기존 노드 후보를 결합한다.

표면형·어휘·문자 trigram·선택적 Embedding·기존 Graph 1-hop·온보딩
관심 시드를 서로 독립된 후보 신호로 보존한다. 이 모듈은 관계를 자동 생성하지
않으며, 외부 Provider나 DB 호출 없이 호출자가 주입한 값만 순수하게 정렬한다.
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass

from agent.wiki_builder.features.identity_resolution import normalize_wiki_surface
from shared.wiki_models import ExistingWikiEntry

type CandidateEmbeddingMap = Mapping["WikiNodeIdentity", Sequence[float]]


@dataclass(frozen=True, slots=True, order=True)
class WikiNodeIdentity:
    """문서 종류와 key로 기존 Wiki 노드를 유일하게 식별한다."""

    document_kind: str
    document_key: str


@dataclass(frozen=True, slots=True)
class RelationCandidateQuery:
    """신규·갱신 노드 하나에서 기존 관계 후보를 찾기 위한 입력."""

    label: str
    aliases: tuple[str, ...] = ()
    context: str = ""
    matched_existing_identity: WikiNodeIdentity | None = None
    embedding: tuple[float, ...] | None = None


@dataclass(frozen=True, slots=True)
class WikiGraphEdge:
    """기존 Wiki Graph에서 후보 확장에 사용할 문서 간 1-hop 연결."""

    source: WikiNodeIdentity
    target: WikiNodeIdentity
    relation_type: str
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class RelationCandidateSignal:
    """후보가 선택된 한 가지 근거와 원점수·가중 기여도."""

    kind: str
    score: float
    contribution: float
    detail: str = ""


@dataclass(frozen=True, slots=True)
class WikiRelationCandidate:
    """LLM 관계 판정에 제공할 기존 Wiki 노드와 결합 점수."""

    entry: ExistingWikiEntry
    score: float
    signals: tuple[RelationCandidateSignal, ...]

    @property
    def identity(self) -> WikiNodeIdentity:
        """후보 문서의 안정적인 종류·key 식별자를 반환한다."""
        return WikiNodeIdentity(self.entry.document_kind, self.entry.document_key)


@dataclass(frozen=True, slots=True)
class RelationCandidateConfig:
    """관계 후보 신호 임계값·가중치·반환 상한 설정."""

    limit: int = 12
    graph_seed_limit: int = 3
    minimum_lexical_score: float = 0.2
    minimum_trigram_score: float = 0.15
    minimum_embedding_score: float = 0.55
    exact_title_weight: float = 0.95
    exact_alias_weight: float = 0.9
    lexical_weight: float = 0.45
    trigram_weight: float = 0.4
    embedding_weight: float = 0.65
    graph_1hop_weight: float = 0.35
    onboarding_anchor_weight: float = 0.25


@dataclass(slots=True)
class _CandidateAccumulator:
    """같은 기존 노드에 들어온 후보 신호를 중복 없이 누적한다."""

    entry: ExistingWikiEntry
    signals: dict[tuple[str, str], RelationCandidateSignal]


_DEFAULT_CONFIG = RelationCandidateConfig()


def _identity(entry: ExistingWikiEntry) -> WikiNodeIdentity:
    """기존 Wiki 문서를 Graph·Embedding Map 공통 식별자로 바꾼다."""
    return WikiNodeIdentity(entry.document_kind, entry.document_key)


def _clamp_score(value: float) -> float:
    """신호 점수를 0과 1 사이의 유한한 값으로 제한한다."""
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


def _metadata_aliases(entry: ExistingWikiEntry) -> tuple[str, ...]:
    """기존 문서 Metadata에서 비어 있지 않은 문자열 별칭을 읽는다."""
    value = entry.metadata.get("aliases", ())
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _unique_texts(items: Iterable[str]) -> tuple[str, ...]:
    """순서를 유지하며 빈 텍스트와 Unicode 표면형 중복을 제거한다."""
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item).strip()
        marker = normalize_wiki_surface(value)
        if value and marker and marker not in seen:
            seen.add(marker)
            result.append(value)
    return tuple(result)


def _query_facets(query: RelationCandidateQuery) -> tuple[str, ...]:
    """후보 비교에 사용할 신규 노드 이름·별칭·설명 조각을 만든다."""
    return _unique_texts((query.label, *query.aliases, query.context))


def _entry_facets(entry: ExistingWikiEntry) -> tuple[str, ...]:
    """후보 비교에 사용할 기존 노드 제목·별칭·분류·요약 조각을 만든다."""
    return _unique_texts(
        (
            entry.title,
            *_metadata_aliases(entry),
            entry.domain or "",
            entry.summary or "",
        )
    )


def _tokenize(value: str) -> set[str]:
    """Unicode 문자열을 공백·구두점 경계의 소문자 검색 토큰으로 나눈다."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    tokens: set[str] = set()
    current: list[str] = []
    for character in normalized:
        if character.isalnum():
            current.append(character)
            continue
        if current:
            tokens.add("".join(current))
            current = []
    if current:
        tokens.add("".join(current))
    return tokens


def _lexical_similarity(left: str, right: str) -> float:
    """짧은 Wiki 이름이 긴 설명에 포함되는 경우를 살리는 토큰 포함도를 계산한다."""
    left_tokens = _tokenize(left)
    right_tokens = _tokenize(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))


def _character_trigrams(value: str) -> set[str]:
    """PostgreSQL pg_trgm과 유사하게 단어 경계를 포함한 문자 trigram을 만든다."""
    surface = normalize_wiki_surface(value)
    if not surface:
        return set()
    padded = f"  {surface} "
    return {padded[index : index + 3] for index in range(len(padded) - 2)}


def _trigram_similarity(left: str, right: str) -> float:
    """두 문자열의 경계 포함 문자 trigram Dice 유사도를 계산한다."""
    left_trigrams = _character_trigrams(left)
    right_trigrams = _character_trigrams(right)
    if not left_trigrams or not right_trigrams:
        return 0.0
    return (2.0 * len(left_trigrams & right_trigrams)) / (
        len(left_trigrams) + len(right_trigrams)
    )


def _maximum_similarity(
    query_facets: Sequence[str],
    entry_facets: Sequence[str],
    similarity: Callable[[str, str], float],
) -> float:
    """신규·기존 노드의 모든 텍스트 조각 중 가장 높은 비교 점수를 찾는다."""
    return max(
        (
            similarity(query_facet, entry_facet)
            for query_facet in query_facets
            for entry_facet in entry_facets
        ),
        default=0.0,
    )


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """같은 차원의 두 주입 Vector 사이 코사인 유사도를 계산한다."""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return _clamp_score(dot / (left_norm * right_norm))


def _make_signal(
    kind: str,
    score: float,
    weight: float,
    *,
    detail: str = "",
) -> RelationCandidateSignal:
    """원점수와 설정 가중치를 안전한 후보 신호로 변환한다."""
    normalized_score = _clamp_score(score)
    return RelationCandidateSignal(
        kind=kind,
        score=normalized_score,
        contribution=_clamp_score(normalized_score * max(0.0, weight)),
        detail=detail,
    )


def _add_signal(
    accumulators: dict[WikiNodeIdentity, _CandidateAccumulator],
    entry: ExistingWikiEntry,
    signal: RelationCandidateSignal,
) -> None:
    """동일 종류·설명의 신호는 더 강한 값만 유지하며 후보에 추가한다."""
    identity = _identity(entry)
    accumulator = accumulators.setdefault(
        identity,
        _CandidateAccumulator(entry=entry, signals={}),
    )
    marker = (signal.kind, signal.detail)
    current = accumulator.signals.get(marker)
    if current is None or signal.contribution > current.contribution:
        accumulator.signals[marker] = signal


def _combined_score(signals: Iterable[RelationCandidateSignal]) -> float:
    """독립 후보 신호를 1을 넘지 않는 확률 합성 방식으로 결합한다."""
    remaining = 1.0
    for signal in signals:
        remaining *= 1.0 - _clamp_score(signal.contribution)
    return 1.0 - remaining


def _rank_accumulators(
    accumulators: Mapping[WikiNodeIdentity, _CandidateAccumulator],
) -> list[WikiRelationCandidate]:
    """누적 후보를 결합 점수와 안정적인 key 순서로 정렬한다."""
    candidates: list[WikiRelationCandidate] = []
    for accumulator in accumulators.values():
        signals = tuple(
            sorted(
                accumulator.signals.values(),
                key=lambda signal: (
                    -signal.contribution,
                    signal.kind,
                    signal.detail,
                ),
            )
        )
        candidates.append(
            WikiRelationCandidate(
                entry=accumulator.entry,
                score=_combined_score(signals),
                signals=signals,
            )
        )
    return sorted(
        candidates,
        key=lambda candidate: (
            -candidate.score,
            -len(candidate.signals),
            candidate.entry.document_kind,
            candidate.entry.document_key,
        ),
    )


def _exact_match_detail(
    query_facets: Sequence[str], candidate_facets: Sequence[str]
) -> str | None:
    """두 텍스트 목록에서 처음 발견한 동일 Unicode 표면형을 설명으로 반환한다."""
    candidate_surfaces = {
        normalize_wiki_surface(value): value for value in candidate_facets
    }
    for query_facet in query_facets:
        marker = normalize_wiki_surface(query_facet)
        if marker and marker in candidate_surfaces:
            return f"{query_facet}={candidate_surfaces[marker]}"
    return None


def _add_direct_signals(
    *,
    query: RelationCandidateQuery,
    entry: ExistingWikiEntry,
    embeddings: CandidateEmbeddingMap,
    config: RelationCandidateConfig,
    accumulators: dict[WikiNodeIdentity, _CandidateAccumulator],
) -> None:
    """표면형·어휘·trigram·Embedding 직접 후보 신호를 계산한다."""
    query_facets = _query_facets(query)
    entry_facets = _entry_facets(entry)
    title_detail = _exact_match_detail(query_facets, (entry.title,))
    if title_detail is not None:
        _add_signal(
            accumulators,
            entry,
            _make_signal(
                "exact_title", 1.0, config.exact_title_weight, detail=title_detail
            ),
        )
    alias_detail = _exact_match_detail(query_facets, _metadata_aliases(entry))
    if alias_detail is not None:
        _add_signal(
            accumulators,
            entry,
            _make_signal(
                "exact_alias", 1.0, config.exact_alias_weight, detail=alias_detail
            ),
        )

    lexical_score = _maximum_similarity(
        query_facets, entry_facets, _lexical_similarity
    )
    if lexical_score >= config.minimum_lexical_score:
        _add_signal(
            accumulators,
            entry,
            _make_signal("lexical", lexical_score, config.lexical_weight),
        )
    trigram_score = _maximum_similarity(
        query_facets, entry_facets, _trigram_similarity
    )
    if trigram_score >= config.minimum_trigram_score:
        _add_signal(
            accumulators,
            entry,
            _make_signal("trigram", trigram_score, config.trigram_weight),
        )

    candidate_embedding = embeddings.get(_identity(entry))
    if query.embedding is None or candidate_embedding is None:
        return
    embedding_score = _cosine_similarity(query.embedding, candidate_embedding)
    if embedding_score >= config.minimum_embedding_score:
        _add_signal(
            accumulators,
            entry,
            _make_signal("embedding", embedding_score, config.embedding_weight),
        )


def _graph_seeds(
    *,
    query: RelationCandidateQuery,
    accumulators: Mapping[WikiNodeIdentity, _CandidateAccumulator],
    config: RelationCandidateConfig,
) -> tuple[WikiNodeIdentity, ...]:
    """명시적 기존 match와 상위 직접 후보에서 1-hop 탐색 시작점을 고른다."""
    seeds: list[WikiNodeIdentity] = []
    if query.matched_existing_identity is not None:
        seeds.append(query.matched_existing_identity)
    for candidate in _rank_accumulators(accumulators):
        identity = candidate.identity
        if identity not in seeds:
            seeds.append(identity)
        if len(seeds) >= max(0, config.graph_seed_limit):
            break
    return tuple(seeds[: max(0, config.graph_seed_limit)])


def _add_graph_signals(
    *,
    graph_edges: Sequence[WikiGraphEdge],
    graph_seeds: Collection[WikiNodeIdentity],
    entries_by_identity: Mapping[WikiNodeIdentity, ExistingWikiEntry],
    excluded_identity: WikiNodeIdentity | None,
    config: RelationCandidateConfig,
    accumulators: dict[WikiNodeIdentity, _CandidateAccumulator],
) -> None:
    """선택된 시작점의 직접 이웃만 후보로 추가하고 2-hop 재확장은 하지 않는다."""
    seed_set = set(graph_seeds)
    for edge in graph_edges:
        if edge.source == edge.target:
            continue
        neighbor: WikiNodeIdentity | None = None
        seed: WikiNodeIdentity | None = None
        if edge.source in seed_set:
            seed, neighbor = edge.source, edge.target
        elif edge.target in seed_set:
            seed, neighbor = edge.target, edge.source
        if neighbor is None or neighbor == excluded_identity:
            continue
        entry = entries_by_identity.get(neighbor)
        if entry is None:
            continue
        detail = (
            f"{edge.source.document_kind}:{edge.source.document_key}"
            f"--{edge.relation_type}-->"
            f"{edge.target.document_kind}:{edge.target.document_key};"
            f"seed={seed.document_kind}:{seed.document_key}"
        )
        _add_signal(
            accumulators,
            entry,
            _make_signal(
                "graph_1hop",
                edge.weight,
                config.graph_1hop_weight,
                detail=detail,
            ),
        )


def retrieve_wiki_relation_candidates(
    query: RelationCandidateQuery,
    existing_entries: Sequence[ExistingWikiEntry],
    *,
    graph_edges: Sequence[WikiGraphEdge] = (),
    onboarding_anchor_ids: Collection[WikiNodeIdentity] = (),
    candidate_embeddings: CandidateEmbeddingMap | None = None,
    config: RelationCandidateConfig = _DEFAULT_CONFIG,
) -> list[WikiRelationCandidate]:
    """여러 검색 신호를 합쳐 LLM 관계 판정용 기존 노드 후보를 반환한다.

    Embedding Vector와 Graph는 호출자가 DB·Provider 경계 밖에서 준비해 주입한다.
    cosine 유사도나 Graph 연결만으로 관계를 생성하지 않으며, 반환된 후보를 후속
    판정기가 검토할 수 있도록 신호별 점수를 그대로 보존한다.

    Args:
        query: 이번 Build에서 추출하거나 갱신한 노드와 선택적 Vector.
        existing_entries: 사용자 Namespace의 기존 entity·concept 문서.
        graph_edges: 기존 관계 Graph의 직접 연결 목록.
        onboarding_anchor_ids: 사용자가 온보딩에서 명시적으로 고른 기존 노드.
        candidate_embeddings: 기존 노드 identity별 사전 계산 Vector.
        config: 신호 임계값·가중치와 최종 후보 상한.

    Returns:
        결합 점수 내림차순의 중복 없는 기존 노드 후보. `limit`을 넘지 않는다.
    """
    if config.limit <= 0 or not query.label.strip():
        return []
    entries_by_identity = {_identity(entry): entry for entry in existing_entries}
    excluded_identity = query.matched_existing_identity
    embeddings = candidate_embeddings or {}
    accumulators: dict[WikiNodeIdentity, _CandidateAccumulator] = {}

    for identity, entry in entries_by_identity.items():
        if identity == excluded_identity:
            continue
        _add_direct_signals(
            query=query,
            entry=entry,
            embeddings=embeddings,
            config=config,
            accumulators=accumulators,
        )

    for anchor_identity in sorted(set(onboarding_anchor_ids)):
        if anchor_identity == excluded_identity:
            continue
        entry = entries_by_identity.get(anchor_identity)
        if entry is None:
            continue
        _add_signal(
            accumulators,
            entry,
            _make_signal(
                "onboarding_anchor",
                1.0,
                config.onboarding_anchor_weight,
                detail=f"{anchor_identity.document_kind}:{anchor_identity.document_key}",
            ),
        )

    seeds = _graph_seeds(query=query, accumulators=accumulators, config=config)
    _add_graph_signals(
        graph_edges=graph_edges,
        graph_seeds=seeds,
        entries_by_identity=entries_by_identity,
        excluded_identity=excluded_identity,
        config=config,
        accumulators=accumulators,
    )
    return _rank_accumulators(accumulators)[: config.limit]


__all__ = [
    "RelationCandidateConfig",
    "RelationCandidateQuery",
    "RelationCandidateSignal",
    "WikiGraphEdge",
    "WikiNodeIdentity",
    "WikiRelationCandidate",
    "retrieve_wiki_relation_candidates",
]
