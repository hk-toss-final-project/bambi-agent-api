"""개인 Wiki 문서·관계 품질 Lint의 결정적 동작을 검증한다."""

from __future__ import annotations

import asyncio

import pytest

from agent.wiki_builder.api import (
    ALLOWED_WIKI_RELATION_TYPES,
    validate_wiki_quality,
    wba_014,
)
from agent.wiki_builder.models import ExistingWikiEntry, WikiRelationPlan


def _entry(
    kind: str,
    key: str,
    title: str,
    *,
    aliases: tuple[str, ...] = (),
    metadata: dict[str, object] | None = None,
) -> ExistingWikiEntry:
    """테스트용 Wiki 문서를 만든다."""
    return ExistingWikiEntry(
        document_kind=kind,
        document_key=key,
        title=title,
        domain="other",
        summary=title,
        metadata={"aliases": list(aliases), **(metadata or {})},
    )


def _relation(
    source_kind: str,
    source_key: str,
    target_kind: str,
    target_key: str,
    relation_type: str,
    *,
    metadata: dict[str, object] | None = None,
) -> WikiRelationPlan:
    """기본 품질 Gate를 통과하는 테스트 관계를 만든다."""
    return WikiRelationPlan(
        source_document_key=source_key,
        source_document_kind=source_kind,
        target_document_key=target_key,
        target_document_kind=target_kind,
        relation_type=relation_type,
        metadata={
            "status": "active",
            "review_status": "accepted",
            "provenance_kind": "source_explicit",
            "confidence": 0.9,
            "evidence": f"{source_key}에서 {target_key}로 이어지는 원문 근거",
            **(metadata or {}),
        },
    )


def test_validate_wiki_quality_accepts_supported_evidenced_cycle() -> None:
    """Ontology·근거·검토 Gate를 통과한 순환 Graph는 오류가 없다."""
    entries = [
        _entry("concept", "weather", "날씨"),
        _entry("concept", "heatwave", "폭염"),
        _entry("concept", "typhoon", "태풍"),
    ]
    relations = [
        _relation("concept", "weather", "concept", "heatwave", "associated_with"),
        _relation("concept", "heatwave", "concept", "typhoon", "associated_with"),
        _relation("concept", "typhoon", "concept", "weather", "associated_with"),
    ]

    report = validate_wiki_quality(entries, relations)

    assert report.passed is True
    assert report.issues == ()
    assert report.metrics["verified_relation_count"] == 3
    assert ALLOWED_WIKI_RELATION_TYPES == {
        "entity_relation",
        "applies_concept",
        "related_concept",
        "alias_of",
        "instance_of",
        "subtopic_of",
        "part_of",
        "located_in",
        "occurs_in",
        "affects",
        "causes",
        "associated_with",
    }


def test_validate_wiki_quality_finds_duplicate_title_and_alias_surfaces() -> None:
    """표기 차이를 정규화해 title·alias가 겹치는 canonical 문서를 찾는다."""
    entries = [
        _entry("concept", "weather-ko", "날 씨", aliases=("Weather",)),
        _entry("concept", "weather-en", "WEATHER!", aliases=("날씨",)),
    ]

    report = validate_wiki_quality(entries, [])

    duplicates = report.issues_for("duplicate_surface")
    assert report.passed is False
    assert len(duplicates) == 2
    assert duplicates[0].document_keys == (
        "concept:weather-en",
        "concept:weather-ko",
    )
    assert report.metrics["duplicate_surface_count"] == 2
    assert report.metrics["orphan_count"] == 2


def test_validate_wiki_quality_rejects_untrusted_relation_lifecycle_states() -> None:
    """미지원·저신뢰·거절·무근거·대체 관계를 각각 별도 문제로 분류한다."""
    entries = [
        _entry("concept", "a", "A"),
        _entry("concept", "b", "B"),
        _entry("concept", "c", "C"),
        _entry("concept", "d", "D"),
        _entry("concept", "e", "E"),
        _entry("concept", "f", "F"),
    ]
    relations = [
        _relation("concept", "a", "concept", "b", "invented_relation"),
        _relation(
            "concept",
            "b",
            "concept",
            "c",
            "associated_with",
            metadata={"confidence": 0.2},
        ),
        _relation(
            "concept",
            "c",
            "concept",
            "d",
            "associated_with",
            metadata={"review_status": "rejected"},
        ),
        _relation(
            "concept",
            "d",
            "concept",
            "e",
            "associated_with",
            metadata={"evidence": ""},
        ),
        _relation(
            "concept",
            "e",
            "concept",
            "f",
            "associated_with",
            metadata={"status": "superseded", "superseded_at": "2026-08-07"},
        ),
    ]

    report = validate_wiki_quality(entries, relations)

    assert report.passed is False
    for code in (
        "unsupported_relation_type",
        "low_confidence_relation",
        "rejected_relation",
        "source_less_relation",
        "superseded_relation",
    ):
        assert len(report.issues_for(code)) == 1
    assert report.metrics["verified_relation_count"] == 0
    assert report.metrics["unsupported_relation_count"] == 1
    assert report.metrics["low_confidence_relation_count"] == 1
    assert report.metrics["rejected_relation_count"] == 1
    assert report.metrics["source_less_relation_count"] == 1
    assert report.metrics["superseded_relation_count"] == 1


def test_validate_wiki_quality_applies_provenance_specific_confidence_floors() -> None:
    """직접 근거와 의미 추론에 Linker와 동일한 신뢰도 기준을 적용한다."""
    entries = [
        _entry("concept", "a", "A"),
        _entry("concept", "b", "B"),
        _entry("concept", "c", "C"),
    ]
    relations = [
        _relation(
            "concept",
            "a",
            "concept",
            "b",
            "associated_with",
            metadata={"confidence": 0.72, "provenance_kind": "source_explicit"},
        ),
        _relation(
            "concept",
            "b",
            "concept",
            "c",
            "associated_with",
            metadata={"confidence": 0.77, "provenance_kind": "semantic_inference"},
        ),
    ]

    report = validate_wiki_quality(entries, relations)

    assert report.metrics["verified_relation_count"] == 1
    assert len(report.issues_for("low_confidence_relation")) == 1
    assert "0.780" in report.issues_for("low_confidence_relation")[0].message


def test_validate_wiki_quality_checks_relation_endpoints_kinds_and_duplicates() -> None:
    """누락 Endpoint, 관계 kind 조합, 자기 관계와 중복 관계를 검출한다."""
    entries = [
        _entry("entity", "seoul", "서울"),
        _entry("concept", "weather", "날씨"),
    ]
    valid = _relation("entity", "seoul", "concept", "weather", "applies_concept")
    relations = [
        valid,
        valid,
        _relation("entity", "seoul", "entity", "seoul", "entity_relation"),
        _relation("concept", "weather", "entity", "seoul", "applies_concept"),
        _relation("concept", "missing", "concept", "weather", "related_concept"),
    ]

    report = validate_wiki_quality(entries, relations)

    assert len(report.issues_for("duplicate_relation")) == 1
    assert len(report.issues_for("self_relation")) == 1
    assert len(report.issues_for("invalid_relation_kind_pair")) == 1
    assert len(report.issues_for("missing_relation_endpoint")) == 1
    assert report.metrics["verified_relation_count"] == 1


def test_validate_wiki_quality_reports_contradictions_and_malformed_metadata() -> None:
    """모순 심각도를 보존하고 잘못된 Metadata는 품질 오류로 처리한다."""
    entries = [
        _entry(
            "concept",
            "weather",
            "날씨",
            metadata={
                "contradictions": [
                    {"severity": "warning", "statement": "관측값 차이"},
                    {"severity": "conflict", "statement": "정의가 상충함"},
                    {"severity": "unknown", "statement": "잘못된 심각도"},
                    "객체가 아닌 항목",
                ]
            },
        )
    ]

    report = validate_wiki_quality(entries, [])

    contradictions = report.issues_for("contradiction")
    assert report.passed is False
    assert [issue.severity for issue in contradictions] == ["error", "warning"]
    assert len(report.issues_for("invalid_contradiction_metadata")) == 2
    assert report.metrics["contradiction_count"] == 2


def test_validate_wiki_quality_uses_verified_inbound_edges_and_finds_dense_hub() -> None:
    """저신뢰 Edge가 고아를 숨기지 않고 검증된 이웃만 Hub degree에 반영된다."""
    entries = [
        _entry("concept", "hub", "허브"),
        _entry("concept", "one", "하나"),
        _entry("concept", "two", "둘"),
        _entry("concept", "three", "셋"),
    ]
    relations = [
        _relation("concept", "hub", "concept", "one", "associated_with"),
        _relation("concept", "hub", "concept", "two", "associated_with"),
        _relation("concept", "hub", "concept", "three", "associated_with"),
        _relation(
            "concept",
            "one",
            "concept",
            "hub",
            "associated_with",
            metadata={"confidence": 0.1},
        ),
    ]

    report = validate_wiki_quality(
        entries,
        relations,
        dense_hub_min_degree=3,
        dense_hub_ratio=1.0,
    )

    assert report.issues_for("dense_hub")[0].document_keys == ("concept:hub",)
    assert {issue.document_keys[0] for issue in report.issues_for("orphan_document")} == {
        "concept:hub"
    }
    assert report.metrics["verified_relation_count"] == 3


def test_wba_014_returns_the_same_typed_quality_report() -> None:
    """비동기 기능 facade가 결정적 검증기의 구조화된 결과를 그대로 반환한다."""
    entries = [_entry("concept", "weather", "날씨")]

    expected = validate_wiki_quality(entries, [])
    actual = asyncio.run(wba_014(entries, []))

    assert actual == expected


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("low_confidence_threshold", -0.1),
        ("dense_hub_min_degree", 0),
        ("dense_hub_ratio", 1.1),
    ],
)
def test_validate_wiki_quality_rejects_invalid_policy(
    keyword: str,
    value: float,
) -> None:
    """운영 임계값 오류를 조용히 보정하지 않고 즉시 알린다."""
    options: dict[str, float] = {keyword: value}

    with pytest.raises(ValueError):
        validate_wiki_quality([], [], **options)  # type: ignore[arg-type]
