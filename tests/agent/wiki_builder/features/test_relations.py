"""개인 Wiki 관계 후보의 참조·유형·원문 근거 검증을 확인한다."""

from agent.wiki_builder.features.relations import parse_relation_candidates


def _refs() -> dict[str, tuple[str, str, str | None]]:
    """관계 검증에 사용할 entity·concept 참조를 반환한다."""
    return {
        "E1": ("entity", "Obsidian", None),
        "E2": ("entity", "Obsidian Web Clipper", None),
        "C1": ("concept", "개인 지식 관리", None),
    }


def test_parse_relation_candidates_accepts_grounded_allowed_relation() -> None:
    """허용된 방향과 원문 근거가 있는 관계를 보존한다."""
    evidence = "Obsidian Web Clipper는 개인 지식 관리에 활용된다."

    result = parse_relation_candidates(
        [
            {
                "source_ref": "E2",
                "target_ref": "C1",
                "relation_type": "applies_concept",
                "evidence": evidence,
            }
        ],
        node_refs=_refs(),
        source_content=evidence,
    )

    assert len(result.relations) == 1
    assert result.relations[0].source_name == "Obsidian Web Clipper"
    assert result.relations[0].target_name == "개인 지식 관리"
    assert result.warnings == []


def test_parse_relation_candidates_rejects_unknown_node_reference() -> None:
    """분류 결과에 없는 노드를 가리키는 관계를 제외한다."""
    result = parse_relation_candidates(
        [
            {
                "source_ref": "E1",
                "target_ref": "E99",
                "relation_type": "entity_relation",
                "evidence": "Obsidian 관계",
            }
        ],
        node_refs=_refs(),
        source_content="Obsidian 관계",
    )

    assert result.relations == []
    assert "존재하지 않는 노드" in result.warnings[0]


def test_parse_relation_candidates_rejects_unsupported_direction() -> None:
    """concept에서 entity로 향하는 비표준 관계를 제외한다."""
    result = parse_relation_candidates(
        [
            {
                "source_ref": "C1",
                "target_ref": "E1",
                "relation_type": "applies_concept",
                "evidence": "개인 지식 관리는 Obsidian에서 사용된다.",
            }
        ],
        node_refs=_refs(),
        source_content="개인 지식 관리는 Obsidian에서 사용된다.",
    )

    assert result.relations == []
    assert "일치하지 않습니다" in result.warnings[0]


def test_parse_relation_candidates_rejects_concept_instance_of_concept() -> None:
    """Concept 간 상하위 관계에 instance_of를 쓰면 제외한다."""
    evidence = "폭염은 날씨 현상이다."
    result = parse_relation_candidates(
        [
            {
                "source_ref": "C1",
                "target_ref": "C2",
                "relation_type": "instance_of",
                "evidence": evidence,
            }
        ],
        node_refs={
            "C1": ("concept", "폭염", None),
            "C2": ("concept", "날씨", "weather"),
        },
        source_content=evidence,
    )

    assert result.relations == []
    assert "일치하지 않습니다" in result.warnings[0]


def test_parse_relation_candidates_rejects_non_verbatim_evidence() -> None:
    """원문에 존재하지 않는 관계 근거를 제외한다."""
    result = parse_relation_candidates(
        [
            {
                "source_ref": "E2",
                "target_ref": "E1",
                "relation_type": "entity_relation",
                "evidence": "원문에 없는 관계다.",
            }
        ],
        node_refs=_refs(),
        source_content="Web Clipper 소개 문서다.",
    )

    assert result.relations == []
    assert "근거가 원문에 존재하지 않습니다" in result.warnings[0]


def test_parse_relation_candidates_allows_whitespace_difference_in_evidence() -> None:
    """원문 줄바꿈을 공백으로 복사한 근거는 같은 문구로 인정한다."""
    result = parse_relation_candidates(
        [
            {
                "source_ref": "E2",
                "target_ref": "E1",
                "relation_type": "entity_relation",
                "evidence": "Web Clipper는 Obsidian에 저장한다.",
            }
        ],
        node_refs=_refs(),
        source_content="Web Clipper는\nObsidian에 저장한다.",
    )

    assert len(result.relations) == 1
    assert result.warnings == []


def test_parse_relation_candidates_removes_self_reference_and_duplicates() -> None:
    """자기 참조를 거부하고 같은 관계는 한 건만 유지한다."""
    relation = {
        "source_ref": "E2",
        "target_ref": "E1",
        "relation_type": "entity_relation",
        "evidence": "Web Clipper는 Obsidian에 저장한다.",
    }
    result = parse_relation_candidates(
        [
            relation,
            relation,
            {
                "source_ref": "E1",
                "target_ref": "E1",
                "relation_type": "entity_relation",
                "evidence": "Web Clipper는 Obsidian에 저장한다.",
            },
        ],
        node_refs=_refs(),
        source_content="Web Clipper는 Obsidian에 저장한다.",
    )

    assert len(result.relations) == 1
    assert any("자기 참조" in warning for warning in result.warnings)


def test_parse_relation_candidates_treats_aliases_of_same_document_as_self() -> None:
    """이름이 달라도 같은 기존 문서 키로 매칭된 노드 관계를 자기 참조로 본다."""
    result = parse_relation_candidates(
        [
            {
                "source_ref": "E1",
                "target_ref": "E2",
                "relation_type": "entity_relation",
                "evidence": "Obsidian은 옵시디언이라는 이름으로도 불린다.",
            }
        ],
        node_refs={
            "E1": ("entity", "Obsidian", "obsidian"),
            "E2": ("entity", "옵시디언", "obsidian"),
        },
        source_content="Obsidian은 옵시디언이라는 이름으로도 불린다.",
    )

    assert result.relations == []
    assert "자기 참조" in result.warnings[0]
