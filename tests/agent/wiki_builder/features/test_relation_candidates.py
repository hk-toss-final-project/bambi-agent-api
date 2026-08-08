"""개인 Wiki 관계 판정용 하이브리드 기존 노드 후보 검색을 검증한다."""

import pytest

from agent.wiki_builder.api import (
    RelationCandidateConfig,
    RelationCandidateQuery,
    WikiGraphEdge,
    WikiNodeIdentity,
    WikiRelationCandidate,
    retrieve_wiki_relation_candidates,
)
from shared.wiki_models import ExistingWikiEntry


def _entry(
    document_kind: str,
    document_key: str,
    title: str,
    *,
    aliases: tuple[str, ...] = (),
    summary: str | None = None,
) -> ExistingWikiEntry:
    """테스트에 사용할 최소 기존 Wiki 문서를 만든다."""
    return ExistingWikiEntry(
        document_kind=document_kind,
        document_key=document_key,
        title=title,
        domain=None,
        summary=summary,
        metadata={"aliases": list(aliases)},
    )


def _signal_kinds(candidate: WikiRelationCandidate) -> set[str]:
    """후보 결과에서 신호 종류 집합을 읽는다."""
    return {signal.kind for signal in candidate.signals}


def test_retrieve_candidates_preserves_exact_title_and_alias_signals() -> None:
    """Unicode 표면형 제목 일치와 별칭 일치를 별도 근거로 보존한다."""
    entries = [
        _entry("concept", "machine-learning", "머신러닝"),
        _entry("entity", "obsidian", "Obsidian", aliases=("옵시디언",)),
    ]

    title_result = retrieve_wiki_relation_candidates(
        RelationCandidateQuery(label="머신 러닝"), entries
    )
    alias_result = retrieve_wiki_relation_candidates(
        RelationCandidateQuery(label="옵시디언"), entries
    )

    assert title_result[0].entry.document_key == "machine-learning"
    assert "exact_title" in _signal_kinds(title_result[0])
    assert alias_result[0].entry.document_key == "obsidian"
    assert "exact_alias" in _signal_kinds(alias_result[0])
    assert all(0.0 <= candidate.score <= 1.0 for candidate in title_result)


def test_retrieve_candidates_uses_lexical_and_character_trigram_signals() -> None:
    """공통 단어와 짧은 한국어 부분 이름을 후보 신호로 함께 계산한다."""
    result = retrieve_wiki_relation_candidates(
        RelationCandidateQuery(label="태풍 돌핀"),
        [_entry("concept", "typhoon", "태풍")],
    )

    assert len(result) == 1
    assert {"lexical", "trigram"} <= _signal_kinds(result[0])


def test_retrieve_candidates_uses_injected_embeddings_only_for_ranking() -> None:
    """주입 Vector의 cosine 유사도는 후보 신호만 만들고 관계를 생성하지 않는다."""
    weather = _entry("concept", "weather", "날씨")
    finance = _entry("concept", "finance", "금융")

    result = retrieve_wiki_relation_candidates(
        RelationCandidateQuery(label="폭염", embedding=(1.0, 0.0)),
        [weather, finance],
        candidate_embeddings={
            WikiNodeIdentity("concept", "weather"): (0.9, 0.1),
            WikiNodeIdentity("concept", "finance"): (0.0, 1.0),
        },
    )

    assert [candidate.entry.document_key for candidate in result] == ["weather"]
    assert _signal_kinds(result[0]) == {"embedding"}
    assert result[0].signals[0].score == pytest.approx(0.9938837)


def test_retrieve_candidates_expands_only_one_graph_hop_from_matched_node() -> None:
    """현재 canonical 노드의 직접 이웃을 추가하되 이웃의 이웃은 확장하지 않는다."""
    seoul_id = WikiNodeIdentity("entity", "seoul")
    heatwave_id = WikiNodeIdentity("concept", "heatwave")
    illness_id = WikiNodeIdentity("concept", "heat-illness")
    entries = [
        _entry("entity", "seoul", "서울"),
        _entry("concept", "heatwave", "폭염"),
        _entry("concept", "heat-illness", "온열질환"),
    ]

    result = retrieve_wiki_relation_candidates(
        RelationCandidateQuery(
            label="서울",
            matched_existing_identity=seoul_id,
        ),
        entries,
        graph_edges=(
            WikiGraphEdge(seoul_id, heatwave_id, "occurs_in"),
            WikiGraphEdge(heatwave_id, illness_id, "affects"),
        ),
    )

    assert [candidate.entry.document_key for candidate in result] == ["heatwave"]
    assert _signal_kinds(result[0]) == {"graph_1hop"}
    assert "entity:seoul--occurs_in-->concept:heatwave" in result[0].signals[0].detail


def test_retrieve_candidates_includes_onboarding_anchor_without_text_match() -> None:
    """온보딩 관심 노드는 원문 단어가 달라도 후속 의미 판정 후보에 포함한다."""
    weather_id = WikiNodeIdentity("concept", "weather")

    result = retrieve_wiki_relation_candidates(
        RelationCandidateQuery(label="폭염"),
        [
            _entry("concept", "weather", "날씨"),
            _entry("concept", "finance", "금융"),
        ],
        onboarding_anchor_ids={weather_id},
    )

    assert [candidate.entry.document_key for candidate in result] == ["weather"]
    assert _signal_kinds(result[0]) == {"onboarding_anchor"}


def test_retrieve_candidates_merges_signals_and_applies_stable_limit() -> None:
    """같은 노드의 여러 근거를 합치고 최종 후보 수를 안정적으로 제한한다."""
    anchor_ids = {
        WikiNodeIdentity("concept", "a"),
        WikiNodeIdentity("concept", "b"),
        WikiNodeIdentity("concept", "c"),
    }
    entries = [
        _entry("concept", "a", "날씨"),
        _entry("concept", "b", "환경"),
        _entry("concept", "c", "재난"),
    ]

    result = retrieve_wiki_relation_candidates(
        RelationCandidateQuery(label="폭염", embedding=(1.0, 0.0)),
        entries,
        onboarding_anchor_ids=anchor_ids,
        candidate_embeddings={
            WikiNodeIdentity("concept", "a"): (1.0, 0.0),
        },
        config=RelationCandidateConfig(limit=2),
    )

    assert [candidate.entry.document_key for candidate in result] == ["a", "b"]
    assert _signal_kinds(result[0]) == {"embedding", "onboarding_anchor"}


def test_retrieve_candidates_excludes_the_matched_existing_node_itself() -> None:
    """현재 노드의 canonical identity는 관계 대상과 온보딩 후보에서 제외한다."""
    weather_id = WikiNodeIdentity("concept", "weather")

    result = retrieve_wiki_relation_candidates(
        RelationCandidateQuery(
            label="날씨",
            matched_existing_identity=weather_id,
        ),
        [_entry("concept", "weather", "날씨")],
        onboarding_anchor_ids={weather_id},
    )

    assert result == []


def test_retrieve_candidates_handles_empty_query_and_zero_limit() -> None:
    """비어 있는 이름이나 0인 상한에는 후보를 만들지 않는다."""
    entries = [_entry("concept", "weather", "날씨")]

    assert (
        retrieve_wiki_relation_candidates(RelationCandidateQuery(label=" "), entries)
        == []
    )
    assert (
        retrieve_wiki_relation_candidates(
            RelationCandidateQuery(label="폭염"),
            entries,
            onboarding_anchor_ids={WikiNodeIdentity("concept", "weather")},
            config=RelationCandidateConfig(limit=0),
        )
        == []
    )
