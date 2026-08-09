"""Personal Wiki Builder 벤치마크의 품질 채점 계약을 검증한다."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bench.wiki_builder import run
from bench.wiki_builder.run import _score
from shared.wiki_models import (
    ConceptClassification,
    ExistingWikiEntry,
    WikiClassification,
    WikiRelationClassification,
    WikiRelationPlan,
)


def _relation() -> WikiRelationClassification:
    """벤치마크 채점에 사용할 검증된 Entity 관계를 반환한다."""
    return WikiRelationClassification(
        source_name="Sam Altman",
        source_kind="entity",
        target_name="OpenAI",
        target_kind="entity",
        relation_type="entity_relation",
        evidence="Sam Altman은 OpenAI의 CEO다.",
    )


def _expected_relation(**overrides: str) -> dict[str, str]:
    """Dataset의 관계 기대값 한 건을 만든다."""
    relation = {
        "source_kind": "entity",
        "source_name": "Sam Altman",
        "target_kind": "entity",
        "target_name": "OpenAI",
        "relation_type": "entity_relation",
    }
    relation.update(overrides)
    return relation


def test_score_requires_expected_wiki_relation() -> None:
    """Dataset에 지정된 관계가 없으면 벤치마크를 실패 처리한다."""
    expected = {"relations": [_expected_relation()]}

    passed, errors, stats = _score(WikiClassification(), expected)

    assert passed is False
    assert errors == ["missing relation: Sam Altman -> OpenAI / entity_relation"]
    assert (stats["tp"], stats["fn"]) == (0, 1)


def test_score_accepts_expected_wiki_relation() -> None:
    """출발·도착 노드와 유형이 일치하는 관계를 성공 처리한다."""
    expected = {
        "relations": [
            _expected_relation(source_name="sam altman", target_name="openai")
        ]
    }

    passed, errors, stats = _score(
        WikiClassification(relations=[_relation()]),
        expected,
    )

    assert passed is True
    assert errors == []
    assert (stats["tp"], stats["fn"]) == (1, 0)


def test_score_rejects_relation_for_isolated_node_case() -> None:
    """관계가 없어야 하는 경계 케이스의 허위 Edge를 실패 처리한다."""
    passed, errors, _ = _score(
        WikiClassification(relations=[_relation()]),
        {"max_relations": 0},
    )

    assert passed is False
    assert errors == ["too many relations: 1"]


def test_score_flags_forbidden_relation() -> None:
    """연결되면 안 되는 쌍을 만들면 금지 위반으로 집계한다."""
    expected = {"forbidden_relations": [_expected_relation()]}

    passed, errors, stats = _score(
        WikiClassification(relations=[_relation()]),
        expected,
    )

    assert passed is False
    assert errors == ["forbidden relation: Sam Altman -> OpenAI"]
    assert stats["forbidden_hit"] == 1


def test_score_flags_forbidden_relation_in_reverse_direction() -> None:
    """금지 쌍은 방향을 뒤집어 연결해도 위반으로 본다."""
    expected = {
        "forbidden_relations": [
            _expected_relation(source_name="OpenAI", target_name="Sam Altman")
        ]
    }

    passed, _errors, stats = _score(
        WikiClassification(relations=[_relation()]),
        expected,
    )

    assert passed is False
    assert stats["forbidden_hit"] == 1


def test_score_counts_reversed_expected_relation_as_missing() -> None:
    """정답 반대 방향 관계는 누락으로 세되 역방향 일치로 표시한다."""
    expected = {
        "relations": [
            _expected_relation(source_name="OpenAI", target_name="Sam Altman")
        ]
    }

    passed, _errors, stats = _score(
        WikiClassification(relations=[_relation()]),
        expected,
    )

    assert passed is False
    assert (stats["fn"], stats["reversed_only"]) == (1, 1)


def test_dataset_covers_incremental_graph_regressions() -> None:
    """부분 누락·온보딩·오연결·병합·고립·stale·degree 회귀를 고정한다."""
    identifiers = {str(case["id"]) for case in run._load_cases()}

    assert {
        "partial-relation-audit",
        "onboarding-weather-anchor",
        "seoul-heat-illness-co-mention",
        "existing-canonical-merge",
        "intentional-standalone",
        "stale-edge-supersession",
        "verified-degree-stability",
        "semantic-inference-provenance",
    } <= identifiers


def test_cost_estimate_requires_nonzero_tokens_and_cost() -> None:
    """실제 LLM 호출 승인 전에 케이스 전체의 예상 비용을 계산한다."""
    input_tokens, output_tokens = run._estimate_tokens(run._load_cases())
    cost = run._estimated_cost(
        input_tokens,
        output_tokens,
        input_cost_per_million=0.40,
        output_cost_per_million=1.60,
    )

    assert input_tokens > 0
    assert output_tokens > 0
    assert cost > 0


def test_runner_includes_onboarding_anchor_in_relation_candidates() -> None:
    """폭염 노드 후보에 어휘가 달라도 온보딩 날씨 anchor를 강제 포함한다."""
    result = WikiClassification(
        concepts=[
            ConceptClassification(
                title="폭염",
                definition="기온이 매우 높은 현상",
            )
        ]
    )
    weather = ExistingWikiEntry(
        document_kind="concept",
        document_key="weather",
        title="날씨",
        domain="field",
        summary="대기의 단기 상태",
        metadata={"source_types": ["onboarding_seed"]},
    )

    candidates = run._relation_candidates(
        result,
        existing_entries=[weather],
        existing_relations=[],
    )

    assert [candidate.entry.document_key for candidate in candidates["N1"]] == [
        "weather"
    ]
    assert {
        signal.kind for signal in candidates["N1"][0].signals
    } >= {"onboarding_anchor"}


def test_score_counts_every_extra_edge_as_false_positive_when_fully_judged() -> None:
    """전수 판정 케이스의 정답 밖 관계를 unsupported false positive로 센다."""
    extra = WikiRelationClassification(
        source_name="OpenAI",
        source_kind="entity",
        target_name="ChatGPT",
        target_kind="entity",
        relation_type="entity_relation",
        evidence="OpenAI는 ChatGPT를 개발했다.",
    )
    expected = {
        "relations": [_expected_relation()],
        "judge_all_relations": True,
    }

    passed, errors, stats = _score(
        WikiClassification(relations=[_relation(), extra]),
        expected,
    )

    assert passed is False
    assert errors == ["unsupported relation: openai -> chatgpt / entity_relation"]
    assert (stats["tp"], stats["fp"], stats["unsupported_edge"]) == (1, 1, 1)


def test_score_forbidden_wildcard_rejects_any_relation_type() -> None:
    """co-mention 금지 쌍은 LLM이 어떤 relation_type을 붙여도 거절한다."""
    expected = {
        "forbidden_relations": [
            {
                "source_kind": "entity",
                "source_name": "Sam Altman",
                "target_kind": "entity",
                "target_name": "OpenAI",
                "relation_type": "*",
            }
        ]
    }

    passed, _errors, stats = _score(
        WikiClassification(relations=[_relation()]),
        expected,
    )

    assert passed is False
    assert (stats["forbidden_hit"], stats["fp"]) == (1, 1)


def test_score_measures_canonical_merge_and_standalone_disposition() -> None:
    """기존 key 병합과 의도적 standalone을 별도 정확도로 측정한다."""
    result = WikiClassification(
        concepts=[
            ConceptClassification(
                title="Weather",
                aliases=["날씨"],
                matched_existing_key="weather",
            ),
            ConceptClassification(title="독립 독서 메모"),
        ]
    )
    expected = {
        "canonical_matches": [
            {"kind": "concept", "name": "날씨", "document_key": "weather"}
        ],
        "dispositions": [
            {"kind": "concept", "name": "날씨", "value": "merge"},
            {
                "kind": "concept",
                "name": "독립 독서 메모",
                "value": "standalone",
                "reason_required": True,
            },
        ],
    }

    passed, errors, stats = _score(result, expected)

    assert passed is True
    assert errors == []
    assert (stats["canonical_correct"], stats["canonical_total"]) == (1, 1)
    assert (stats["disposition_correct"], stats["disposition_total"]) == (2, 2)


def test_score_excludes_superseded_edge_from_active_and_verified_degree() -> None:
    """stale 관계 row를 보존해도 active·verified degree에는 포함하지 않는다."""
    superseded = WikiRelationPlan(
        source_document_key="seoul",
        source_document_kind="entity",
        target_document_key="heat-illness",
        target_document_kind="concept",
        relation_type="applies_concept",
        metadata={
            "status": "superseded",
            "review_status": "rejected",
            "confidence": 0.95,
        },
    )
    accepted = WikiRelationPlan(
        source_document_key="kdca",
        source_document_kind="entity",
        target_document_key="heat-illness",
        target_document_kind="concept",
        relation_type="applies_concept",
        metadata={
            "status": "active",
            "review_status": "accepted",
            "confidence": 0.92,
        },
    )
    plan = SimpleNamespace(
        relations=[superseded, accepted],
        isolated_node_count=1,
    )
    expected = {
        "removed_relations": [
            {
                "source_kind": "entity",
                "source_key": "seoul",
                "target_kind": "concept",
                "target_key": "heat-illness",
                "relation_type": "applies_concept",
            }
        ],
        "active_degree_by_document": {
            "entity:seoul": 0,
            "entity:kdca": 1,
            "concept:heat-illness": 1,
        },
        "verified_degree_by_document": {
            "entity:seoul": 0,
            "entity:kdca": 1,
            "concept:heat-illness": 1,
        },
        "isolated_node_count": 1,
    }

    passed, errors, stats = _score(
        WikiClassification(),
        expected,
        plan=plan,
        relation_state=[superseded, accepted],
    )

    assert passed is True
    assert errors == []
    assert (stats["stale_correct"], stats["stale_total"]) == (1, 1)
    assert (stats["degree_correct"], stats["degree_total"]) == (6, 6)


def test_score_requires_authoritative_relation_state_for_lifecycle_metrics() -> None:
    """plan만으로 stale support를 추정하지 않고 DB 관계 상태를 요구한다."""
    expected = {"active_degree_by_document": {"entity:seoul": 0}}

    passed, errors, stats = _score(WikiClassification(), expected)

    assert passed is False
    assert errors == [
        "relation lifecycle state unavailable: "
        "sync_wiki_relation_supports 이후 active head 조회가 필요합니다."
    ]
    assert (stats["degree_correct"], stats["degree_total"]) == (0, 1)


def test_runner_requires_relation_state_fixture_before_llm_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """lifecycle Fixture가 없으면 비용 승인 여부와 무관하게 LLM 전에 중단한다."""
    called = False

    def fail_if_called(*_args: object, **_kwargs: object) -> object:
        """사전 검증 전에 LLM 경계가 호출되면 테스트를 실패시킨다."""
        nonlocal called
        called = True
        raise AssertionError("LLM must not be called")

    def fake_args() -> SimpleNamespace:
        """비용까지 승인했지만 Fixture는 빠진 실행 인자를 반환한다."""
        return SimpleNamespace(
            model="test-model",
            input_cost_per_million=0.0,
            output_cost_per_million=0.0,
            relation_state_fixture=None,
            confirm_cost=True,
        )

    def fake_cases() -> list[dict[str, object]]:
        """권위 관계 상태가 필요한 최소 lifecycle 케이스를 반환한다."""
        return [
            {
                "id": "needs-state",
                "input": {"title": "상태 필요", "content": "본문"},
                "expected": {
                    "active_degree_by_document": {"concept:weather": 0}
                },
            }
        ]

    monkeypatch.setattr(run, "_args", fake_args)
    monkeypatch.setattr(run, "_load_cases", fake_cases)
    monkeypatch.setattr(run, "complete_with_usage", fail_if_called)

    with pytest.raises(SystemExit, match="relation-state-fixture"):
        run.main()

    assert called is False


def test_loads_fingerprinted_post_sync_active_head_fixture() -> None:
    """동봉 Fixture가 모든 lifecycle 케이스의 active head 상태를 제공한다."""
    cases = run._load_cases()

    provider = run._load_authoritative_relation_states(
        cases,
        run.ROOT / "relation_state_fixture.json",
    )

    assert provider is not None
    assert set(provider.states_by_case) == {
        "stale-edge-supersession",
        "verified-degree-stability",
    }
    assert provider.sha256
    assert {
        relation.metadata["status"]
        for relations in provider.states_by_case.values()
        for relation in relations
    } == {"active"}


def test_loaded_fixture_scores_stale_and_degree_contracts() -> None:
    """Fixture 상태로 stale 제거와 active·verified degree를 결정적으로 채점한다."""
    cases = run._load_cases()
    cases_by_id = {str(case["id"]): case for case in cases}
    provider = run._load_authoritative_relation_states(
        cases,
        run.ROOT / "relation_state_fixture.json",
    )
    assert provider is not None

    for case_id in ("stale-edge-supersession", "verified-degree-stability"):
        expected = cases_by_id[case_id]["expected"]
        lifecycle_expected = {
            key: expected[key]
            for key in (
                "removed_relations",
                "active_degree_by_document",
                "verified_degree_by_document",
                "verified_degree_min_confidence",
            )
            if key in expected
        }
        passed, errors, _stats = _score(
            WikiClassification(),
            lifecycle_expected,
            relation_state=provider.for_case(case_id),
        )

        assert passed is True
        assert errors == []


def test_rejects_relation_state_fixture_after_dataset_drift(
    tmp_path: Path,
) -> None:
    """데이터셋 입력·기대값과 fingerprint가 어긋난 Fixture를 거절한다."""
    fixture = json.loads(
        (run.ROOT / "relation_state_fixture.json").read_text(encoding="utf-8")
    )
    fixture["cases"]["stale-edge-supersession"]["case_fingerprint"] = "stale"
    fixture_path = tmp_path / "relation_state_fixture.json"
    fixture_path.write_text(
        json.dumps(fixture, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="fingerprint"):
        run._load_authoritative_relation_states(run._load_cases(), fixture_path)


def test_rejects_non_active_relation_in_authoritative_fixture(
    tmp_path: Path,
) -> None:
    """active head 조회에 나올 수 없는 superseded 관계가 있으면 거절한다."""
    fixture = json.loads(
        (run.ROOT / "relation_state_fixture.json").read_text(encoding="utf-8")
    )
    relation = fixture["cases"]["stale-edge-supersession"]["relations"][0]
    relation["metadata"]["status"] = "superseded"
    fixture_path = tmp_path / "relation_state_fixture.json"
    fixture_path.write_text(
        json.dumps(fixture, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="status는 active"):
        run._load_authoritative_relation_states(run._load_cases(), fixture_path)


def test_score_validates_relation_provenance_fields() -> None:
    """관계별 provenance·confidence·review 계약을 독립 지표로 검증한다."""
    relation = SimpleNamespace(
        source_name="폭염",
        source_kind="concept",
        target_name="날씨",
        target_kind="concept",
        relation_type="subtopic_of",
        evidence="폭염은 기온이 매우 높은 날씨 현상이다.",
        provenance_kind="source_explicit",
        confidence=0.91,
        review_status="accepted",
        rationale="폭염은 날씨 현상의 하위 주제다.",
        status="active",
        metadata={},
    )
    result = SimpleNamespace(
        entities=[],
        concepts=[],
        relations=[relation],
        source_summary="",
    )
    expected = {
        "relations": [
            {
                "source_kind": "concept",
                "source_name": "폭염",
                "target_kind": "concept",
                "target_name": "날씨",
                "relation_type": "subtopic_of",
            }
        ],
        "relation_attributes": [
            {
                "relation": {
                    "source_kind": "concept",
                    "source_name": "폭염",
                    "target_kind": "concept",
                    "target_name": "날씨",
                    "relation_type": "subtopic_of",
                },
                "attributes": {
                    "provenance_kind": "source_explicit",
                    "confidence": 0.91,
                    "confidence_min": 0.7,
                    "review_status": "accepted",
                    "rationale_required": True,
                },
            }
        ],
    }

    passed, errors, stats = _score(result, expected)

    assert passed is True
    assert errors == []
    assert (
        stats["relation_attribute_correct"],
        stats["relation_attribute_total"],
    ) == (5, 5)
