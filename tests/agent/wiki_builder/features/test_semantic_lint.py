"""Personal Wiki V3 의미 감사 입력과 전역 후보 생성을 검증한다."""

from datetime import UTC, datetime

import pytest

from agent.wiki_builder.features.semantic_lint import (
    WikiSemanticLintLimits,
    WikiSemanticSourceDocument,
    build_global_relation_candidates,
    build_wiki_semantic_lint_context,
)
from shared.wiki_models import ExistingWikiEntry, WikiRelationPlan


def _entry(
    kind: str,
    key: str,
    title: str,
    *,
    summary: str = "",
    aliases: list[str] | None = None,
    sources: list[str] | None = None,
    related_entities: list[str] | None = None,
    related_concepts: list[str] | None = None,
) -> ExistingWikiEntry:
    """테스트용 Wiki Page를 만든다."""
    return ExistingWikiEntry(
        document_kind=kind,
        document_key=key,
        title=title,
        domain="other",
        summary=summary,
        metadata={
            "aliases": aliases or [],
            "sources": sources or [],
            "related_entities": related_entities or [],
            "related_concepts": related_concepts or [],
        },
    )


def _relation(
    source_kind: str,
    source_key: str,
    target_kind: str,
    target_key: str,
) -> WikiRelationPlan:
    """테스트용 검증 관계를 만든다."""
    return WikiRelationPlan(
        source_document_kind=source_kind,
        source_document_key=source_key,
        target_document_kind=target_kind,
        target_document_key=target_key,
        relation_type="associated_with",
        metadata={"status": "active", "review_status": "accepted"},
    )


def test_context_assigns_stable_references_and_limits_source_content() -> None:
    """Page·원본 참조는 입력 순서와 무관하고 원문 상한을 지킨다."""
    entries = [
        _entry("concept", "zeta", "제타"),
        _entry("entity", "alpha", "알파"),
        _entry("concept", "beta", "베타"),
    ]
    sources = [
        WikiSemanticSourceDocument(
            source_document_version_id="version-b",
            title="일반 원본",
            raw_content="일반 본문은 길다",
        ),
        WikiSemanticSourceDocument(
            source_document_version_id="version-a",
            title="온보딩",
            raw_content="관심주제전체",
            source_type="onboarding_seed",
            published_at=datetime(2026, 8, 12, tzinfo=UTC),
        ),
    ]

    context = build_wiki_semantic_lint_context(
        entries,
        [],
        sources,
        limits=WikiSemanticLintLimits(
            page_limit=2,
            source_limit=2,
            source_chars=4,
            candidates_per_page=0,
        ),
    )

    assert [
        (page.reference, page.document_kind, page.document_key)
        for page in context.pages
    ] == [("P1", "concept", "beta"), ("P2", "concept", "zeta")]
    assert [source.reference for source in context.sources] == ["S1", "S2"]
    assert context.sources[0].source_document_version_id == "version-a"
    assert context.sources[0].content == "관심주제"


def test_declared_related_page_becomes_high_priority_candidate() -> None:
    """Metadata가 가리키지만 Edge가 없는 Page 쌍을 최우선 후보로 만든다."""
    context = build_wiki_semantic_lint_context(
        [
            _entry(
                "concept",
                "agent",
                "AI 에이전트",
                related_concepts=["검색 증강 생성"],
            ),
            _entry(
                "concept",
                "rag",
                "RAG",
                aliases=["검색 증강 생성"],
            ),
        ],
        [],
        [],
    )

    assert len(context.relation_candidates) == 1
    candidate = context.relation_candidates[0]
    assert candidate.reference == "C1"
    assert candidate.score == pytest.approx(0.95)
    assert "declared_related_page" in candidate.signals


def test_existing_relation_pair_is_not_proposed_in_either_direction() -> None:
    """이미 연결된 두 Page는 관계 유형과 방향에 무관하게 후보에서 제외한다."""
    pages_context = build_wiki_semantic_lint_context(
        [
            _entry(
                "entity",
                "seoul",
                "서울",
                sources=["[[sources/weather|날씨]]"],
                related_concepts=["날씨"],
            ),
            _entry(
                "concept",
                "weather",
                "날씨",
                sources=["[[sources/weather|날씨]]"],
            ),
        ],
        [_relation("concept", "weather", "entity", "seoul")],
        [],
    )

    assert pages_context.relation_candidates == ()


def test_shared_source_and_common_neighbor_signals_are_combined() -> None:
    """공유 출처와 공통 이웃을 가진 미연결 Page 쌍에 두 신호를 보존한다."""
    shared = "[[sources/agents|에이전트 글]]"
    context = build_wiki_semantic_lint_context(
        [
            _entry("concept", "agent", "AI 에이전트", sources=[shared]),
            _entry("concept", "rag", "RAG", sources=[shared]),
            _entry("concept", "retrieval", "정보 검색"),
        ],
        [
            _relation("concept", "agent", "concept", "retrieval"),
            _relation("concept", "rag", "concept", "retrieval"),
        ],
        [],
    )

    candidate = next(
        candidate
        for candidate in context.relation_candidates
        if {
            candidate.source_page_reference,
            candidate.target_page_reference,
        }
        == {"P1", "P2"}
    )
    assert "shared_source:1" in candidate.signals
    assert "common_neighbor:1" in candidate.signals


def test_relation_candidate_limit_is_deterministic() -> None:
    """후보 전역 상한은 점수와 안정적인 참조 순서로 일관되게 적용한다."""
    pages = build_wiki_semantic_lint_context(
        [
            _entry(
                "concept",
                f"topic-{index}",
                f"주제 {index}",
                sources=["[[sources/shared|공유]]"],
            )
            for index in range(5)
        ],
        [],
        [],
        limits=WikiSemanticLintLimits(
            candidates_per_page=2,
            relation_candidate_limit=3,
        ),
    )

    assert [candidate.reference for candidate in pages.relation_candidates] == [
        "C1",
        "C2",
        "C3",
    ]
    assert [
        (candidate.source_page_reference, candidate.target_page_reference)
        for candidate in pages.relation_candidates
    ] == [("P1", "P2"), ("P1", "P3"), ("P1", "P4")]


def test_build_global_candidates_returns_empty_when_disabled() -> None:
    """Page별 후보 또는 전역 상한이 0이면 후보 계산을 건너뛴다."""
    context = build_wiki_semantic_lint_context(
        [_entry("concept", "a", "A"), _entry("concept", "b", "B")],
        [],
        [],
    )

    assert build_global_relation_candidates(
        context.pages,
        [],
        per_page_limit=0,
    ) == ()


@pytest.mark.parametrize(
    "field",
    [
        "page_limit",
        "source_limit",
        "source_chars",
        "candidates_per_page",
        "relation_candidate_limit",
    ],
)
def test_negative_semantic_lint_limit_is_rejected(field: str) -> None:
    """음수 상한은 조용히 슬라이스 의미로 해석하지 않는다."""
    values = {
        "page_limit": 80,
        "source_limit": 24,
        "source_chars": 2_400,
        "candidates_per_page": 4,
        "relation_candidate_limit": 40,
    }
    values[field] = -1

    with pytest.raises(ValueError, match=field):
        build_wiki_semantic_lint_context(
            [],
            [],
            [],
            limits=WikiSemanticLintLimits(**values),
        )
