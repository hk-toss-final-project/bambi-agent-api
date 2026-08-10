"""개인 Wiki 중복 문서 병합 계획(PWIKI-009)을 검증한다."""

import asyncio

import pytest

from domain.personal_wiki.documents.features.merging import (
    CrossKindMergeError,
    pwiki_009,
)
from shared.wiki_models import ExistingWikiEntry, WikiRelationPlan


def _entry(
    key: str,
    title: str,
    *,
    kind: str = "concept",
    domain: str | None = None,
    summary: str | None = None,
    metadata: dict[str, object] | None = None,
) -> ExistingWikiEntry:
    """테스트용 기존 Wiki 문서 한 건을 만든다."""
    return ExistingWikiEntry(
        document_kind=kind,
        document_key=key,
        title=title,
        domain=domain,
        summary=summary,
        metadata=metadata or {},
    )


def _relation(
    source: str,
    target: str,
    *,
    source_kind: str = "concept",
    target_kind: str = "concept",
    relation_type: str = "related_concept",
    metadata: dict[str, object] | None = None,
) -> WikiRelationPlan:
    """테스트용 Wiki 관계 한 건을 만든다."""
    return WikiRelationPlan(
        source_document_key=source,
        source_document_kind=source_kind,
        target_document_key=target,
        target_document_kind=target_kind,
        relation_type=relation_type,
        metadata=metadata or {},
    )


def test_absorbs_duplicate_title_and_aliases_without_losing_existing() -> None:
    """흡수한 문서의 제목·별칭이 기존 별칭 뒤에 append-only로 붙는다."""
    winner = _entry(
        "machine-learning",
        "머신러닝",
        metadata={"aliases": ["Machine Learning"]},
    )
    duplicate = _entry(
        "machine-learning-2",
        "머신 러닝",
        metadata={"aliases": ["ML"]},
    )

    plan = asyncio.run(pwiki_009(winner, [duplicate]))

    assert plan.metadata["aliases"] == ["Machine Learning", "머신 러닝", "ML"]
    assert plan.added_alias_count == 2
    assert plan.retired_document_keys == ("machine-learning-2",)
    assert plan.document_key == "machine-learning"


def test_identical_duplicate_title_is_not_added_as_alias() -> None:
    """canonical 제목과 같은 제목은 별칭으로 다시 추가하지 않는다."""
    winner = _entry("weather", "날씨")
    duplicate = _entry("weather-2", "날씨")

    plan = asyncio.run(pwiki_009(winner, [duplicate]))

    assert plan.metadata.get("aliases", []) == []
    assert plan.added_alias_count == 0


def test_spacing_variant_title_is_preserved_as_alias() -> None:
    """띄어쓰기만 다른 표기는 사용자가 쓴 표기이므로 별칭으로 보존한다."""
    winner = _entry("machine-learning", "머신러닝")
    duplicate = _entry("machine-learning-2", "머신 러닝")

    plan = asyncio.run(pwiki_009(winner, [duplicate]))

    assert plan.metadata["aliases"] == ["머신 러닝"]


def test_sources_are_appended_and_deduplicated() -> None:
    """출처는 덮어쓰지 않고 중복 없이 이어 붙인다."""
    winner = _entry("seoul", "서울", metadata={"sources": ["sources/a"]})
    duplicate = _entry(
        "seoul-2", "서울시", metadata={"sources": ["sources/a", "sources/b"]}
    )

    plan = asyncio.run(pwiki_009(winner, [duplicate]))

    assert plan.metadata["sources"] == ["sources/a", "sources/b"]
    assert plan.added_source_count == 1


def test_reviewed_winner_keeps_domain_and_summary() -> None:
    """사람이 검증한 문서의 domain·summary는 흡수 대상이 덮어쓰지 못한다."""
    winner = _entry(
        "weather",
        "날씨",
        summary="사람이 검증한 요약",
        domain="climate",
        metadata={"reviewed": True},
    )
    duplicate = _entry(
        "weather-2", "기상", summary="자동 생성 요약", domain="science"
    )

    plan = asyncio.run(pwiki_009(winner, [duplicate]))

    assert plan.summary == "사람이 검증한 요약"
    assert plan.domain == "climate"
    assert plan.reviewed_preserved is True
    # 덮어쓰지 않더라도 흡수된 내용은 출처와 함께 남아야 한다.
    assert plan.merged_from[0]["summary"] == "자동 생성 요약"


def test_unreviewed_winner_fills_missing_domain_and_summary() -> None:
    """검증되지 않은 문서의 빈 값만 흡수 대상에서 채운다."""
    winner = _entry("weather", "날씨", summary=None, domain=None)
    duplicate = _entry(
        "weather-2", "기상", summary="흡수된 요약", domain="climate"
    )

    plan = asyncio.run(pwiki_009(winner, [duplicate]))

    assert plan.summary == "흡수된 요약"
    assert plan.domain == "climate"
    assert plan.reviewed_preserved is False


def test_relations_are_repointed_to_canonical_document() -> None:
    """흡수 대상을 가리키던 관계가 canonical 문서로 옮겨진다."""
    winner = _entry("weather", "날씨")
    duplicate = _entry("weather-2", "기상")
    relations = [_relation("heatwave", "weather-2")]

    plan = asyncio.run(pwiki_009(winner, [duplicate], relations))

    assert len(plan.relations) == 1
    assert plan.relations[0].target_document_key == "weather"
    assert plan.relations[0].source_document_key == "heatwave"
    assert plan.rewritten_relation_count == 1


def test_relation_between_merged_documents_is_dropped() -> None:
    """병합으로 자기 자신을 가리키게 된 관계는 저장 대상에서 제외한다."""
    winner = _entry("weather", "날씨")
    duplicate = _entry("weather-2", "기상")
    relations = [_relation("weather", "weather-2")]

    plan = asyncio.run(pwiki_009(winner, [duplicate], relations))

    assert plan.relations == ()
    assert plan.dropped_relation_count == 1


def test_duplicate_relation_signature_keeps_highest_confidence() -> None:
    """같은 서명이 된 관계는 신뢰도가 가장 높은 한 건만 남는다."""
    winner = _entry("weather", "날씨")
    duplicate = _entry("weather-2", "기상")
    relations = [
        _relation("heatwave", "weather", metadata={"confidence": 0.72}),
        _relation("heatwave", "weather-2", metadata={"confidence": 0.95}),
    ]

    plan = asyncio.run(pwiki_009(winner, [duplicate], relations))

    assert len(plan.relations) == 1
    assert plan.relations[0].metadata["confidence"] == 0.95
    assert plan.dropped_relation_count == 1


def test_relation_rewrite_is_order_independent() -> None:
    """입력 관계 순서가 달라도 같은 병합 결과를 만든다."""
    winner = _entry("weather", "날씨")
    duplicate = _entry("weather-2", "기상")
    first = _relation("heatwave", "weather", metadata={"confidence": 0.72})
    second = _relation("heatwave", "weather-2", metadata={"confidence": 0.95})

    forward = asyncio.run(pwiki_009(winner, [duplicate], [first, second]))
    reverse = asyncio.run(pwiki_009(winner, [duplicate], [second, first]))

    assert forward.relations == reverse.relations


def test_unrelated_relations_are_preserved() -> None:
    """병합과 무관한 관계는 그대로 유지한다."""
    winner = _entry("weather", "날씨")
    duplicate = _entry("weather-2", "기상")
    relations = [_relation("typhoon", "ocean")]

    plan = asyncio.run(pwiki_009(winner, [duplicate], relations))

    assert plan.relations == (relations[0],)
    assert plan.rewritten_relation_count == 0
    assert plan.dropped_relation_count == 0


def test_existing_contradictions_are_inherited_without_new_ones() -> None:
    """기존 모순 기록만 이어받고 병합이 새 모순을 만들지 않는다."""
    winner = _entry(
        "weather",
        "날씨",
        summary="맑음",
        metadata={"contradictions": [{"severity": "warning", "message": "기존"}]},
    )
    duplicate = _entry(
        "weather-2",
        "기상",
        summary="흐림",
        metadata={"contradictions": [{"severity": "warning", "message": "흡수"}]},
    )

    plan = asyncio.run(pwiki_009(winner, [duplicate]))

    assert plan.metadata["contradictions"] == [
        {"severity": "warning", "message": "기존"},
        {"severity": "warning", "message": "흡수"},
    ]


def test_multiple_duplicates_are_absorbed_in_order() -> None:
    """중복 문서가 여러 건이어도 순서대로 모두 흡수한다."""
    winner = _entry("weather", "날씨")
    duplicates = [_entry("weather-2", "기상"), _entry("weather-3", "웨더")]

    plan = asyncio.run(pwiki_009(winner, duplicates))

    assert plan.retired_document_keys == ("weather-2", "weather-3")
    assert plan.metadata["aliases"] == ["기상", "웨더"]


def test_winner_listed_as_duplicate_is_ignored() -> None:
    """canonical 문서가 중복 목록에 섞여 있어도 스스로를 폐기하지 않는다."""
    winner = _entry("weather", "날씨")
    duplicates = [winner, _entry("weather-2", "기상")]

    plan = asyncio.run(pwiki_009(winner, duplicates))

    assert plan.retired_document_keys == ("weather-2",)


def test_repeated_duplicate_key_is_absorbed_once() -> None:
    """같은 중복 문서를 여러 번 넘겨도 한 번만 흡수한다."""
    winner = _entry("weather", "날씨")
    duplicate = _entry("weather-2", "기상")

    plan = asyncio.run(pwiki_009(winner, [duplicate, duplicate]))

    assert plan.retired_document_keys == ("weather-2",)
    assert plan.added_alias_count == 1


def test_cross_kind_merge_is_rejected() -> None:
    """entity와 concept 병합은 관계 의미 재판정이 필요해 거절한다."""
    winner = _entry("seoul", "서울", kind="entity")
    duplicate = _entry("seoul-concept", "서울", kind="concept")

    with pytest.raises(CrossKindMergeError):
        asyncio.run(pwiki_009(winner, [duplicate]))


def test_empty_duplicates_are_rejected() -> None:
    """흡수할 중복 문서가 없으면 병합 계획을 만들지 않는다."""
    winner = _entry("weather", "날씨")

    with pytest.raises(ValueError):
        asyncio.run(pwiki_009(winner, []))


def test_unsupported_document_kind_is_rejected() -> None:
    """entity·concept가 아닌 문서 종류는 병합 대상이 아니다."""
    winner = _entry("schema", "Schema", kind="schema")

    with pytest.raises(ValueError):
        asyncio.run(pwiki_009(winner, [_entry("schema-2", "Schema2", kind="schema")]))


def test_winner_metadata_is_not_mutated() -> None:
    """호출자가 넘긴 원본 Metadata를 병합이 직접 수정하지 않는다."""
    winner = _entry("weather", "날씨", metadata={"aliases": ["Weather"]})
    duplicate = _entry("weather-2", "기상")

    asyncio.run(pwiki_009(winner, [duplicate]))

    assert winner.metadata == {"aliases": ["Weather"]}
