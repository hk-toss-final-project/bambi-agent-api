"""개인 지식 Wiki LLM 분류기를 검증한다. 실제 LLM은 호출하지 않는다."""

import json

import pytest

from agent.wiki_builder.features import classification as llm_wiki
from agent.wiki_builder.models import ExistingWikiEntry


def _fake_response(
    entities: list[dict] | None = None,
    concepts: list[dict] | None = None,
    source_summary: str = "",
) -> str:
    """테스트용 LLM JSON 응답을 만든다."""
    return json.dumps(
        {
            "source_summary": source_summary,
            "entities": entities or [],
            "concepts": concepts or [],
        }
    )


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
