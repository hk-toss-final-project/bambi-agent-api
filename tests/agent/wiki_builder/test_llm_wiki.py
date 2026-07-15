"""agent/wiki_builder/llm_wiki.py를 검증한다. 실제 LLM은 호출하지 않는다."""

import json

import pytest

from agent.wiki_builder import llm_wiki
from agent.wiki_builder.models import ExistingWikiEntry


def _fake_response(entities: list[dict] | None = None, concepts: list[dict] | None = None) -> str:
    return json.dumps({"entities": entities or [], "concepts": concepts or []})


def test_parse_wiki_classification_maps_full_entity_and_concept() -> None:
    """모든 필드가 채워진 응답을 데이터클래스로 정확히 변환한다."""
    raw = _fake_response(
        entities=[
            {
                "name": "wiki_documents",
                "domain": "지식 문서",
                "role": "Wiki 문서 Head 관리",
                "columns": ["id", "document_kind"],
                "relations": ["wiki_document_versions와 1:N"],
                "related_concepts": ["Versioned Configuration"],
                "matched_existing_key": None,
                "is_alias": False,
            }
        ],
        concepts=[
            {
                "title": "Versioned Configuration",
                "summary": "덮어쓰지 않고 새 버전을 추가한다.",
                "explanation": "이력 보존과 감사 추적을 위해서다.",
                "related_entity_names": ["wiki_documents", "prompt_templates"],
                "matched_existing_key": "versioned-configuration",
                "overlaps_existing": True,
            }
        ],
    )

    result = llm_wiki.parse_wiki_classification(raw)

    assert len(result.entities) == 1
    entity = result.entities[0]
    assert entity.name == "wiki_documents"
    assert entity.domain == "지식 문서"
    assert entity.columns == ["id", "document_kind"]
    assert entity.matched_existing_key is None
    assert entity.is_alias is False

    assert len(result.concepts) == 1
    concept = result.concepts[0]
    assert concept.title == "Versioned Configuration"
    assert concept.matched_existing_key == "versioned-configuration"
    assert concept.overlaps_existing is True


def test_parse_wiki_classification_defaults_missing_optional_fields() -> None:
    """선택 필드가 빠져도 안전한 기본값으로 채운다."""
    raw = json.dumps({"entities": [{"name": "이름만 있음"}], "concepts": []})

    result = llm_wiki.parse_wiki_classification(raw)

    entity = result.entities[0]
    assert entity.domain == "미분류"
    assert entity.role == ""
    assert entity.columns == []
    assert entity.relations == []
    assert entity.related_concepts == []
    assert entity.matched_existing_key is None
    assert entity.is_alias is False


def test_parse_wiki_classification_strips_markdown_code_fence() -> None:
    """```json 코드펜스로 감싼 응답도 그대로 파싱한다."""
    raw = f"```json\n{_fake_response()}\n```"

    result = llm_wiki.parse_wiki_classification(raw)

    assert result.entities == []
    assert result.concepts == []


def test_parse_wiki_classification_rejects_invalid_json() -> None:
    """JSON이 아닌 응답은 의미 있는 오류로 실패한다."""
    with pytest.raises(ValueError, match="JSON"):
        llm_wiki.parse_wiki_classification("이것은 JSON이 아닙니다")


def test_parse_wiki_classification_rejects_non_object_json() -> None:
    """JSON 배열처럼 객체가 아닌 최상위 값은 오류로 처리한다."""
    with pytest.raises(ValueError, match="JSON 객체"):
        llm_wiki.parse_wiki_classification("[1, 2, 3]")


def test_classify_source_for_wiki_sends_source_and_existing_context(monkeypatch) -> None:
    """원본 본문과 기존 entity·concept 목록이 프롬프트에 그대로 전달된다."""
    captured: dict[str, str] = {}

    def fake_complete(system_prompt: str, user_prompt: str, model: str = "gpt-4.1-mini") -> str:
        captured["system"] = system_prompt
        captured["user"] = user_prompt
        captured["model"] = model
        return _fake_response()

    monkeypatch.setattr(llm_wiki, "complete", fake_complete)

    existing_entities = [ExistingWikiEntry("entity", "wiki-documents", "wiki_documents", "지식 문서", "요약")]
    existing_concepts = [ExistingWikiEntry("concept", "versioned-configuration", "Versioned Configuration", None, None)]

    result = llm_wiki.classify_source_for_wiki(
        source_title="클리핑: pgvector 소개",
        source_content="pgvector는 PostgreSQL Extension이다.",
        existing_entities=existing_entities,
        existing_concepts=existing_concepts,
        model="gpt-4.1-mini",
    )

    assert result.entities == []
    assert "클리핑: pgvector 소개" in captured["user"]
    assert "pgvector는 PostgreSQL Extension이다." in captured["user"]
    assert "key=wiki-documents" in captured["user"]
    assert "key=versioned-configuration" in captured["user"]
    assert "entity 판단 기준" in captured["system"]
    assert "concept 판단 기준" in captured["system"]
    assert captured["model"] == "gpt-4.1-mini"


def test_classify_source_for_wiki_notes_when_no_existing_context(monkeypatch) -> None:
    """기존 entity·concept이 없으면 '(없음)'을 프롬프트에 명시한다."""
    captured: dict[str, str] = {}

    def fake_complete(system_prompt: str, user_prompt: str, model: str = "gpt-4.1-mini") -> str:
        captured["user"] = user_prompt
        return _fake_response()

    monkeypatch.setattr(llm_wiki, "complete", fake_complete)

    llm_wiki.classify_source_for_wiki(
        source_title="새 원본",
        source_content="본문",
        existing_entities=[],
        existing_concepts=[],
    )

    assert captured["user"].count("(없음)") == 2


def test_classify_source_for_wiki_trims_overly_long_content(monkeypatch) -> None:
    """지나치게 긴 원본은 상한 문자 수로 잘라 비용·지연을 제한한다."""
    captured: dict[str, str] = {}

    def fake_complete(system_prompt: str, user_prompt: str, model: str = "gpt-4.1-mini") -> str:
        captured["user"] = user_prompt
        return _fake_response()

    monkeypatch.setattr(llm_wiki, "complete", fake_complete)

    long_content = "가" * 10_000
    llm_wiki.classify_source_for_wiki(
        source_title="긴 원본",
        source_content=long_content,
        existing_entities=[],
        existing_concepts=[],
    )

    assert "가" * 8000 in captured["user"]
    assert "가" * 8001 not in captured["user"]
