"""LLM Wiki 분류 호출.

사용자 원본 한 건과 Namespace에 이미 있는 entity·concept 목록을 LLM에 전달해,
Agent DB Wiki 생성 규칙서의 entity/concept 판단 체크리스트에 따라 신규 생성·기존
갱신·병합(동의어·중복) 여부를 분류한다. 실제 Provider 호출은 저수준 경계인
agent.assistant.summarize.complete로 위임해, 테스트에서 이 함수만 대체하면 실제
호출 없이 검증할 수 있다.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from agent.assistant.summarize import complete
from agent.wiki_builder.models import (
    ConceptClassification,
    EntityClassification,
    ExistingWikiEntry,
    WikiClassification,
)

# 요약·보고서 생성과 동일한 상한으로, 지나치게 긴 원본이 비용·지연을 키우지 않게 자른다.
_MAX_SOURCE_CHARS = 8000

_SYSTEM_PROMPT = (
    "너는 Agent DB Wiki 생성 규칙서에 따라 사용자 원본 문서를 개인 LLM Wiki의 "
    "entity/concept 후보로 분류하는 한국어 비서다. 원본에 실제로 있는 내용만 사용하고 "
    "없는 사실을 지어내지 않는다.\n\n"
    "[entity 판단 기준]\n"
    "- 원본에 등장하는 구체적인 대상(개념적 실체, 시스템 구성요소, 테이블 등)마다 "
    "entity 후보 하나를 만든다.\n"
    "- 이미 제공된 기존 entity와 이름만 다른 동일 대상이면 새로 만들지 말고 "
    "matched_existing_key에 그 document_key를 채우고 is_alias=true로 표시한다.\n"
    "- 기존 entity와 구조가 실질적으로 같지만 완전한 동의어는 아니면 "
    "matched_existing_key만 채우고 is_alias=false로 표시해 병합 검토 대상임을 알린다.\n\n"
    "[concept 판단 기준]\n"
    "- concept은 둘 이상의 entity가 공유하는 설계 패턴에만 부여한다. entity 하나에만 "
    "해당하는 내용은 concept으로 만들지 말고 해당 entity의 역할/설명에만 반영한다.\n"
    "- '왜 이렇게 설계했는지' 트레이드오프를 설명할 수 있는 내용만 concept 자격이 있다. "
    "단순 컬럼 나열이나 사실 요약은 concept으로 만들지 않는다.\n"
    "- 이미 제공된 기존 concept과 70% 이상 겹치면 새로 만들지 말고 "
    "matched_existing_key를 채우고 overlaps_existing=true로 표시한다.\n\n"
    "반드시 아래 JSON 형식 하나만 출력한다. 다른 설명이나 Markdown 코드펜스를 덧붙이지 않는다.\n"
    "{\n"
    '  "entities": [\n'
    "    {\n"
    '      "name": "string", "domain": "string", "role": "string",\n'
    '      "columns": ["string"], "relations": ["string"], "related_concepts": ["string"],\n'
    '      "matched_existing_key": "string 또는 null", "is_alias": true\n'
    "    }\n"
    "  ],\n"
    '  "concepts": [\n'
    "    {\n"
    '      "title": "string", "summary": "string", "explanation": "string",\n'
    '      "related_entity_names": ["string"],\n'
    '      "matched_existing_key": "string 또는 null", "overlaps_existing": true\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "새 entity/concept이 없으면 해당 목록을 빈 배열로 둔다."
)


def _format_existing_entries(entries: Sequence[ExistingWikiEntry]) -> str:
    """이미 존재하는 entity·concept 목록을 프롬프트용 텍스트로 정리한다."""
    if not entries:
        return "(없음)"
    lines = []
    for entry in entries:
        summary = f" — {entry.summary}" if entry.summary else ""
        domain = f" [domain={entry.domain}]" if entry.domain else ""
        lines.append(f"- key={entry.document_key}: {entry.title}{domain}{summary}")
    return "\n".join(lines)


def _strip_json_fence(raw: str) -> str:
    """LLM이 Markdown 코드펜스로 감싼 JSON을 반환해도 그대로 파싱할 수 있게 벗긴다."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").strip()
        text = text.removesuffix("```").strip()
    return text


def _parse_entity(raw: dict[str, object]) -> EntityClassification:
    """LLM 출력의 entity 항목 하나를 EntityClassification으로 변환한다."""
    return EntityClassification(
        name=str(raw.get("name") or "").strip(),
        domain=str(raw.get("domain") or "").strip() or "미분류",
        role=str(raw.get("role") or "").strip(),
        columns=[str(item) for item in (raw.get("columns") or [])],
        relations=[str(item) for item in (raw.get("relations") or [])],
        related_concepts=[str(item) for item in (raw.get("related_concepts") or [])],
        matched_existing_key=(str(raw["matched_existing_key"]) if raw.get("matched_existing_key") else None),
        is_alias=bool(raw.get("is_alias", False)),
    )


def _parse_concept(raw: dict[str, object]) -> ConceptClassification:
    """LLM 출력의 concept 항목 하나를 ConceptClassification으로 변환한다."""
    return ConceptClassification(
        title=str(raw.get("title") or "").strip(),
        summary=str(raw.get("summary") or "").strip(),
        explanation=str(raw.get("explanation") or "").strip(),
        related_entity_names=[str(item) for item in (raw.get("related_entity_names") or [])],
        matched_existing_key=(str(raw["matched_existing_key"]) if raw.get("matched_existing_key") else None),
        overlaps_existing=bool(raw.get("overlaps_existing", False)),
    )


def parse_wiki_classification(raw_response: str) -> WikiClassification:
    """LLM의 원시 응답 문자열을 검증된 WikiClassification으로 파싱한다."""
    text = _strip_json_fence(raw_response)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"LLM Wiki 분류 응답이 JSON 형식이 아닙니다: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("LLM Wiki 분류 응답이 JSON 객체가 아닙니다.")

    entities = [_parse_entity(item) for item in (payload.get("entities") or []) if isinstance(item, dict)]
    concepts = [_parse_concept(item) for item in (payload.get("concepts") or []) if isinstance(item, dict)]
    return WikiClassification(entities=entities, concepts=concepts)


def classify_source_for_wiki(
    *,
    source_title: str,
    source_content: str,
    existing_entities: Sequence[ExistingWikiEntry],
    existing_concepts: Sequence[ExistingWikiEntry],
    model: str = "gpt-4.1-mini",
) -> WikiClassification:
    """사용자 원본 한 건을 entity/concept 후보로 분류해 WikiClassification을 반환한다.

    Args:
        source_title: user_source_document_versions.title
        source_content: user_source_document_versions.raw_content
        existing_entities: Namespace에 이미 있는 entity 목록(중복 판단용 Context)
        existing_concepts: Namespace에 이미 있는 concept 목록(중복 판단용 Context)
        model: 분류에 사용할 OpenAI 모델 이름

    Returns:
        entity·concept 후보와 각각의 신규/갱신/병합 판단을 담은 WikiClassification
    """
    trimmed = source_content.strip()[:_MAX_SOURCE_CHARS]
    user_prompt = (
        f"[원본 제목]\n{source_title}\n\n"
        f"[원본 본문]\n{trimmed or '(본문 없음)'}\n\n"
        f"[기존 entity 목록]\n{_format_existing_entries(existing_entities)}\n\n"
        f"[기존 concept 목록]\n{_format_existing_entries(existing_concepts)}"
    )
    raw_response = complete(_SYSTEM_PROMPT, user_prompt, model=model)
    return parse_wiki_classification(raw_response)
