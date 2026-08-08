"""Wiki identity 판정 벤치마크 데이터와 채점기를 검증한다."""

import json
from pathlib import Path

from bench.wiki_identity_resolution.run import _score
from shared.wiki_models import ConceptClassification, EntityClassification, WikiClassification


def test_identity_resolution_dataset_has_required_edge_cases() -> None:
    """최소 10개와 한영 혼용·동음이의어·주입 경계 케이스를 유지한다."""
    dataset = (
        Path(__file__).parents[2]
        / "bench"
        / "wiki_identity_resolution"
        / "dataset.jsonl"
    )
    cases = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines()]

    assert len(cases) >= 10
    ids = {case["id"] for case in cases}
    assert {"translation-alias-cross-kind", "apple-company", "prompt-injection-content"} <= ids


def test_score_accepts_expected_existing_concept() -> None:
    """기대 kind와 기존 key가 일치하는 canonical Concept를 통과시킨다."""
    passed, errors = _score(
        WikiClassification(
            concepts=[
                ConceptClassification(
                    title="머신 러닝",
                    matched_existing_key="머신-러닝",
                )
            ]
        ),
        {
            "document_kind": "concept",
            "document_key": "머신-러닝",
            "node_count": 1,
        },
    )

    assert passed is True
    assert errors == []


def test_score_rejects_wrong_namespace_even_with_same_key() -> None:
    """동일 key여도 entity/concept namespace가 다르면 실패시킨다."""
    passed, errors = _score(
        WikiClassification(
            entities=[
                EntityClassification(
                    name="머신 러닝",
                    matched_existing_key="머신-러닝",
                )
            ]
        ),
        {
            "document_kind": "concept",
            "document_key": "머신-러닝",
            "node_count": 1,
        },
    )

    assert passed is False
    assert errors == ["missing kind: concept"]
