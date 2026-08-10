"""개인 지식 Wiki LLM 분류기를 검증한다. 실제 LLM은 호출하지 않는다."""

import json

import pytest

from agent.wiki_builder.features import classification as llm_wiki
from agent.wiki_builder.models import ExistingWikiEntry


def _fake_response(
    entities: list[dict] | None = None,
    concepts: list[dict] | None = None,
    relations: list[dict] | None = None,
    source_summary: str = "",
) -> str:
    """테스트용 LLM JSON 응답을 만든다."""
    return json.dumps(
        {
            "source_summary": source_summary,
            "entities": entities or [],
            "concepts": concepts or [],
            "relations": relations or [],
        }
    )


def test_classify_legacy_onboarding_seed_preserves_official_compound_label() -> None:
    """구버전 시드도 정식 복합 명칭을 임의로 쪼개지 않고 Concept로 변환한다."""
    result = llm_wiki.classify_onboarding_seed_for_wiki(
        {"labels": ["AI·머신러닝", "반도체", "AI·머신러닝", " "]}
    )

    assert result.entities == []
    assert [concept.title for concept in result.concepts] == ["AI·머신러닝", "반도체"]
    assert [concept.definition for concept in result.concepts] == [
        "사용자가 온보딩에서 직접 선택한 관심 주제: AI·머신러닝",
        "사용자가 온보딩에서 직접 선택한 관심 주제: 반도체",
    ]
    assert "AI·머신러닝" in result.source_summary
    assert all(concept.subtype == "term" for concept in result.concepts)


@pytest.mark.parametrize("metadata", [{}, {"labels": []}, {"labels": [" "]}])
def test_classify_onboarding_seed_rejects_missing_labels(
    metadata: dict[str, object],
) -> None:
    """유효 라벨이 없는 손상된 온보딩 시드는 명시적으로 거절한다."""
    with pytest.raises(ValueError, match="온보딩 시드"):
        llm_wiki.classify_onboarding_seed_for_wiki(metadata)


def test_parse_wiki_classification_maps_personal_knowledge_fields() -> None:
    """개인 지식 entity·concept 필드를 데이터 객체로 변환한다."""
    raw = _fake_response(
        source_summary="Obsidian은 노트 연결 도구다.",
        entities=[
            {
                "name": "Obsidian",
                "subtype": "product",
                "description": "Markdown 기반 지식 관리 도구다.",
                "aliases": ["옵시디언"],
                "related_entity_names": ["Obsidian Web Clipper"],
                "related_concepts": ["연결 노트"],
                "mentions": ["Obsidian은 Markdown 기반이다."],
                "matched_existing_key": None,
                "is_alias": False,
            }
        ],
        concepts=[
            {
                "title": "연결 노트",
                "subtype": "method",
                "definition": "노트 사이를 링크로 연결하는 방법이다.",
                "key_characteristics": ["양방향 링크"],
                "applications": ["개인 지식 관리"],
                "related_entity_names": ["Obsidian"],
                "related_concepts": ["지식 그래프"],
                "aliases": ["linked notes"],
                "mentions": ["노트를 서로 연결한다."],
            }
        ],
    )

    result = llm_wiki.parse_wiki_classification(raw)

    assert result.source_summary == "Obsidian은 노트 연결 도구다."
    assert result.entities[0].subtype == "product"
    assert result.entities[0].aliases == ["옵시디언"]
    assert result.concepts[0].subtype == "method"
    assert result.concepts[0].key_characteristics == ["양방향 링크"]


def test_parse_wiki_classification_maps_grounded_relations() -> None:
    """응답 내부 참조와 원문 근거가 유효한 관계를 노드 연결로 변환한다."""
    evidence = "Obsidian Web Clipper는 Obsidian에 웹 페이지를 저장한다."
    raw = _fake_response(
        entities=[
            {"ref": "E1", "name": "Obsidian Web Clipper"},
            {"ref": "E2", "name": "Obsidian"},
        ],
        relations=[
            {
                "source_ref": "E1",
                "target_ref": "E2",
                "relation_type": "entity_relation",
                "evidence": evidence,
            }
        ],
    )

    result = llm_wiki.parse_wiki_classification(raw, source_content=evidence)

    assert len(result.relations) == 1
    assert result.relations[0].source_name == "Obsidian Web Clipper"
    assert result.relations[0].target_name == "Obsidian"
    assert result.entities[0].related_entity_names == ["Obsidian"]
    assert result.relation_warnings == []


def test_parse_wiki_classification_normalizes_invalid_subtypes() -> None:
    """허용되지 않은 subtype은 other로 정규화한다."""
    raw = _fake_response(
        entities=[{"name": "대상", "subtype": "company"}],
        concepts=[{"title": "개념", "subtype": "idea"}],
    )

    result = llm_wiki.parse_wiki_classification(raw)

    assert result.entities[0].subtype == "other"
    assert result.concepts[0].subtype == "other"


def test_parse_wiki_classification_keeps_only_verbatim_mentions() -> None:
    """원문에 없는 인용문을 제거한다."""
    raw = _fake_response(
        entities=[
            {
                "name": "Obsidian",
                "mentions": ["원문에 있는 문장", "만들어낸 문장"],
            }
        ]
    )

    result = llm_wiki.parse_wiki_classification(
        raw, source_content="여기에 원문에 있는 문장이 있다."
    )

    assert result.entities[0].mentions == ["원문에 있는 문장"]


def test_parse_wiki_classification_strips_markdown_code_fence() -> None:
    """JSON 코드펜스로 감싼 응답도 파싱한다."""
    result = llm_wiki.parse_wiki_classification(
        f"```json\n{_fake_response()}\n```"
    )

    assert result.entities == []
    assert result.concepts == []


def test_parse_wiki_classification_rejects_invalid_json() -> None:
    """JSON이 아닌 응답은 의미 있는 오류로 실패한다."""
    with pytest.raises(ValueError, match="JSON"):
        llm_wiki.parse_wiki_classification("이것은 JSON이 아닙니다")


def test_parse_wiki_classification_rejects_non_object_json() -> None:
    """최상위 JSON 배열을 거부한다."""
    with pytest.raises(ValueError, match="JSON 객체"):
        llm_wiki.parse_wiki_classification("[1, 2, 3]")


def test_classify_source_for_wiki_sends_metadata_and_existing_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """원본 Metadata와 기존 Wiki Context를 프롬프트에 포함한다."""
    captured: dict[str, str] = {}

    def fake_complete(
        system_prompt: str, user_prompt: str, model: str = "gpt-4.1-mini"
    ) -> str:
        """호출 인자를 저장하는 테스트 LLM이다."""
        captured["system"] = system_prompt
        captured["user"] = user_prompt
        captured["model"] = model
        return _fake_response()

    monkeypatch.setattr(llm_wiki, "complete", fake_complete)
    existing_entities = [
        ExistingWikiEntry(
            "entity",
            "obsidian",
            "Obsidian",
            "product",
            "Markdown 노트 도구",
            {"aliases": ["옵시디언"]},
        )
    ]

    llm_wiki.classify_source_for_wiki(
        source_title="Obsidian Web Clipper",
        source_content="웹 페이지를 Markdown으로 저장한다.",
        source_description="웹 클리핑 도구",
        source_tags=["clippings", "pkm"],
        existing_entities=existing_entities,
        existing_concepts=[],
    )

    assert "웹 클리핑 도구" in captured["user"]
    assert "clippings, pkm" in captured["user"]
    assert "key=obsidian" in captured["user"]
    assert "aliases=옵시디언" in captured["user"]
    assert "사람, 조직, 프로젝트" in captured["system"]
    assert "별도 Relation Linker" in captured["system"]


def test_classify_source_for_wiki_processes_all_long_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """8,000자를 넘는 원문을 버리지 않고 여러 호출로 처리한다."""
    prompts: list[str] = []

    def fake_complete(
        system_prompt: str, user_prompt: str, model: str = "gpt-4.1-mini"
    ) -> str:
        """청크별 프롬프트를 수집하는 테스트 LLM이다."""
        prompts.append(user_prompt)
        return _fake_response(source_summary=f"요약 {len(prompts)}")

    monkeypatch.setattr(llm_wiki, "complete", fake_complete)
    source = "가" * 10_000

    result = llm_wiki.classify_source_for_wiki(
        source_title="긴 원본",
        source_content=source,
        existing_entities=[],
        existing_concepts=[],
    )

    assert len(prompts) == 2
    assert sum(prompt.count("가") for prompt in prompts) == len(source)
    assert result.source_summary == "요약 1\n\n요약 2"


def test_classify_source_for_wiki_leaves_relations_to_separate_linker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """노드 추출 호출은 Edge 유무와 무관하게 관계 판정을 수행하지 않는다."""
    response = _fake_response(
        entities=[
            {"name": "Sam Altman", "subtype": "person"},
            {"name": "OpenAI", "subtype": "organization"},
        ]
    )
    calls: list[str] = []

    def fake_complete(
        system_prompt: str, user_prompt: str, model: str = "gpt-4.1-mini"
    ) -> str:
        """노드 추출 응답 하나만 반환한다."""
        calls.append(system_prompt)
        return response

    monkeypatch.setattr(llm_wiki, "complete", fake_complete)

    result = llm_wiki.classify_source_for_wiki(
        source_title="OpenAI",
        source_content="Sam Altman은 OpenAI의 CEO다.",
        existing_entities=[],
        existing_concepts=[],
    )

    assert len(calls) == 1
    assert result.relations == []
    assert result.relation_warnings == []


def test_classify_source_for_wiki_discards_legacy_relation_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """구버전 응답의 부분 관계가 노드 Markdown 연결 필드에도 남지 않는다."""
    evidence = "Sam Altman은 OpenAI를 이끈다."
    response = _fake_response(
        entities=[
            {"ref": "E1", "name": "Sam Altman", "subtype": "person"},
            {"ref": "E2", "name": "OpenAI", "subtype": "organization"},
        ],
        relations=[
            {
                "source_ref": "E1",
                "target_ref": "E2",
                "relation_type": "entity_relation",
                "evidence": evidence,
            }
        ],
    )

    def fake_complete(
        system_prompt: str, user_prompt: str, model: str = "gpt-4.1-mini"
    ) -> str:
        """구버전 관계 필드를 포함한 추출 응답을 반환한다."""
        return response

    monkeypatch.setattr(llm_wiki, "complete", fake_complete)

    result = llm_wiki.classify_source_for_wiki(
        source_title="OpenAI",
        source_content=evidence,
        existing_entities=[],
        existing_concepts=[],
    )

    assert result.relations == []
    assert all(not entity.related_entity_names for entity in result.entities)
    assert all(not entity.related_concepts for entity in result.entities)


def test_classify_source_for_wiki_does_not_decide_isolation_during_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """고립 여부는 후속 Linker가 후보 검토 후 결정하도록 비워 둔다."""
    response = _fake_response(
        entities=[
            {"name": "서로 무관한 대상 A"},
            {"name": "서로 무관한 대상 B"},
        ]
    )

    def fake_complete(
        system_prompt: str, user_prompt: str, model: str = "gpt-4.1-mini"
    ) -> str:
        """관계 필드가 없는 노드 추출 응답을 반환한다."""
        return response

    monkeypatch.setattr(llm_wiki, "complete", fake_complete)

    result = llm_wiki.classify_source_for_wiki(
        source_title="무관한 대상",
        source_content="대상 A와 대상 B를 각각 기록했다.",
        existing_entities=[],
        existing_concepts=[],
    )

    assert result.relations == []
    assert result.relation_warnings == []
    assert result.node_dispositions == []


def test_split_source_content_preserves_internal_whitespace() -> None:
    """긴 원문의 문단 구분과 청크 경계 공백을 손실 없이 보존한다."""
    source = "  첫 문단\n\n" + ("가" * 8_010) + "\n마지막 문단  "

    chunks = llm_wiki.split_source_content(source)

    assert len(chunks) == 2
    assert "".join(chunks) == source.strip()


def test_merge_wiki_classifications_merges_duplicate_entities() -> None:
    """청크 간 동일 entity의 설명·별칭·인용을 합친다."""
    first = llm_wiki.parse_wiki_classification(
        _fake_response(
            entities=[
                {
                    "name": "Obsidian",
                    "description": "노트 도구다.",
                    "aliases": ["옵시디언"],
                }
            ]
        )
    )
    second = llm_wiki.parse_wiki_classification(
        _fake_response(
            entities=[
                {
                    "name": "Obsidian",
                    "description": "링크를 지원한다.",
                    "aliases": ["옵시디언"],
                }
            ]
        )
    )

    merged = llm_wiki.merge_wiki_classifications([first, second])

    assert len(merged.entities) == 1
    assert "노트 도구다." in merged.entities[0].description
    assert "링크를 지원한다." in merged.entities[0].description
    assert merged.entities[0].aliases == ["옵시디언"]
