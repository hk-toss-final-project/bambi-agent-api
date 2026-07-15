"""개인 지식 Wiki Vault Markdown 렌더링 기능 구현.

LLM이 분류한 entity·concept·source를 검증 가능한 Obsidian Markdown으로
변환한다. 날짜·출처·태그와 같은 시스템 값은 LLM 출력을 신뢰하지 않고
렌더러가 직접 주입한다.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Sequence

from agent.wiki_builder.models import ExistingWikiEntry, WikiRelationPlan

SCHEMA_DOCUMENT_KEY = "root"
SCHEMA_FILE_PATH = "schema/schema.md"

_SLUG_COLLAPSE = re.compile(r"-{2,}")


def _is_slug_character(character: str) -> bool:
    """원문 문자, 결합 문자와 Emoji Symbol을 slug에 보존할지 판단한다."""
    category = unicodedata.category(character)
    return character.isalnum() or category.startswith(("M", "S")) or character == "\u200d"


def slugify(name: str) -> str:
    """Wiki document_key와 파일명에 쓸 안정적인 slug를 만든다."""
    normalized = "".join(
        character if _is_slug_character(character) else "-"
        for character in name.strip()
    ).strip("-")
    normalized = _SLUG_COLLAPSE.sub("-", normalized).lower()
    if not normalized:
        raise ValueError(f"빈 이름은 document_key로 변환할 수 없습니다: {name!r}")
    return normalized


def compute_content_hash(content: str) -> str:
    """문서 본문의 64자 SHA-256 무결성 Hash를 계산한다."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def entity_file_path(document_key: str) -> str:
    """entity 문서의 Vault 경로를 만든다."""
    return f"entities/{document_key}.md"


def concept_file_path(document_key: str) -> str:
    """concept 문서의 Vault 경로를 만든다."""
    return f"concepts/{document_key}.md"


def source_file_path(source_title: str, content_hash: str) -> str:
    """출처 제목과 내용 Hash로 충돌하지 않는 source 경로를 만든다."""
    suffix = content_hash[:6] if content_hash else compute_content_hash(source_title)[:6]
    return f"sources/{slugify(source_title)}_{suffix}.md"


def _yaml(value: object) -> str:
    """문자열·목록을 YAML과 호환되는 JSON 표현으로 변환한다."""
    return json.dumps(value, ensure_ascii=False)


def _unique(items: Iterable[str]) -> list[str]:
    """순서를 유지하며 빈 문자열과 중복을 제거한다."""
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = item.strip()
        marker = value.casefold()
        if value and marker not in seen:
            seen.add(marker)
            result.append(value)
    return result


def _bullet_block(items: Iterable[str], empty_text: str) -> str:
    """문자열 목록을 Markdown Bullet로 변환하고 빈 목록은 안내문을 쓴다."""
    lines = [f"- {item}" for item in items]
    return "\n".join(lines) if lines else empty_text


def _entity_link(name: str) -> str:
    """entity 이름을 경로가 포함된 Obsidian Wiki Link로 변환한다."""
    return f"[[entities/{slugify(name)}|{name}]]"


def _concept_link(name: str) -> str:
    """concept 이름을 경로가 포함된 Obsidian Wiki Link로 변환한다."""
    return f"[[concepts/{slugify(name)}|{name}]]"


def render_entity_markdown(
    *,
    name: str,
    subtype: str,
    description: str,
    aliases: Sequence[str],
    related_entities: Sequence[str],
    related_concepts: Sequence[str],
    mention_entries: Sequence[tuple[str, str]],
    source_links: Sequence[str],
    source_title: str,
    source_link: str,
    created: str,
    updated: str,
) -> str:
    """개인 지식 Wiki의 entity 템플릿으로 Markdown을 만든다."""
    sources = _unique([*source_links, source_link])
    mention_lines = [
        f'"{quote}" — {mention_source}'
        for quote, mention_source in dict.fromkeys(mention_entries)
    ]
    return (
        "---\n"
        "type: entity\n"
        f"created: {_yaml(created)}\n"
        f"updated: {_yaml(updated)}\n"
        f"sources: {_yaml(sources)}\n"
        f"tags: {_yaml([subtype])}\n"
        f"aliases: {_yaml(_unique(aliases))}\n"
        "generation_complete: true\n"
        "---\n"
        "## Basic Information\n"
        f"- Type: {subtype}\n"
        f"- Source: {source_link}\n"
        "## Description\n"
        f"{description or '(설명 없음)'}\n"
        "## Related Entities\n"
        f"{_bullet_block((_entity_link(item) for item in _unique(related_entities)), '(No related entities)')}\n"
        "## Related Concepts\n"
        f"{_bullet_block((_concept_link(item) for item in _unique(related_concepts)), '(No related concepts)')}\n"
        "## Mentions in Source\n"
        f"{_bullet_block(mention_lines, '(No verbatim mentions)')}\n"
    )


def render_concept_markdown(
    *,
    title: str,
    subtype: str,
    definition: str,
    key_characteristics: Sequence[str],
    applications: Sequence[str],
    aliases: Sequence[str],
    related_entities: Sequence[str],
    related_concepts: Sequence[str],
    mention_entries: Sequence[tuple[str, str]],
    source_links: Sequence[str],
    source_link: str,
    created: str,
    updated: str,
) -> str:
    """개인 지식 Wiki의 concept 템플릿으로 Markdown을 만든다."""
    sources = _unique([*source_links, source_link])
    mention_lines = [
        f'"{quote}" — {mention_source}'
        for quote, mention_source in dict.fromkeys(mention_entries)
    ]
    return (
        "---\n"
        "type: concept\n"
        f"created: {_yaml(created)}\n"
        f"updated: {_yaml(updated)}\n"
        f"sources: {_yaml(sources)}\n"
        f"tags: {_yaml([subtype])}\n"
        f"aliases: {_yaml(_unique(aliases))}\n"
        "generation_complete: true\n"
        "---\n"
        "## Definition\n"
        f"{definition or '(정의 없음)'}\n"
        "## Key Characteristics\n"
        f"{_bullet_block(_unique(key_characteristics), '(No key characteristics)')}\n"
        "## Applications\n"
        f"{_bullet_block(_unique(applications), '(No applications)')}\n"
        "## Related Concepts\n"
        f"{_bullet_block((_concept_link(item) for item in _unique(related_concepts)), '(No related concepts)')}\n"
        "## Related Entities\n"
        f"{_bullet_block((_entity_link(item) for item in _unique(related_entities)), '(No related entities)')}\n"
        "## Mentions in Source\n"
        f"{_bullet_block(mention_lines, '(No verbatim mentions)')}\n"
    )


def render_schema_markdown(
    *,
    entities: Sequence[ExistingWikiEntry],
    concepts: Sequence[ExistingWikiEntry],
    relations: Sequence[WikiRelationPlan],
) -> str:
    """Namespace의 entity·concept·관계를 한눈에 보는 Schema Markdown을 만든다."""
    lines = ["---", "type: schema", "generation_complete: true", "---", "# Schema", "", "## Entities"]
    if entities:
        by_subtype: dict[str, list[ExistingWikiEntry]] = {}
        for entry in entities:
            by_subtype.setdefault(entry.domain or "other", []).append(entry)
        for subtype in sorted(by_subtype):
            lines.append(f"### {subtype}")
            lines.extend(
                f"- [[entities/{entry.document_key}|{entry.title}]]"
                for entry in sorted(by_subtype[subtype], key=lambda item: item.document_key)
            )
    else:
        lines.append("- (No entities)")
    lines.extend(["", "## Concepts"])
    if concepts:
        lines.extend(
            f"- [[concepts/{entry.document_key}|{entry.title}]]"
            for entry in sorted(concepts, key=lambda item: item.document_key)
        )
    else:
        lines.append("- (No concepts)")
    lines.extend(["", "## Relations"])
    if relations:
        folder_by_kind = {"entity": "entities", "concept": "concepts"}
        lines.extend(
            f"- [[{folder_by_kind[relation.source_document_kind]}/{relation.source_document_key}]] "
            f"--{relation.relation_type}--> "
            f"[[{folder_by_kind[relation.target_document_kind]}/{relation.target_document_key}]]"
            for relation in relations
        )
    else:
        lines.append("- (No relations)")
    lines.append("")
    return "\n".join(lines)


def render_index_markdown(
    *,
    entities: Sequence[ExistingWikiEntry],
    concepts: Sequence[ExistingWikiEntry],
    source_entries: Sequence[tuple[str, str]],
) -> str:
    """entity·concept·source 문서를 연결하는 Wiki index.md를 만든다."""
    lines = ["# Wiki Index", "> Auto-generated knowledge base directory", "", "## Entities"]
    lines.extend(
        (
            f"- [[entities/{entry.document_key}|{entry.title}]]"
            + (
                f" `aliases: {', '.join(str(item) for item in entry.metadata.get('aliases', []))}`"
                if entry.metadata.get("aliases")
                else ""
            )
            + " - type: entity"
        )
        for entry in sorted(entities, key=lambda item: item.document_key)
    )
    lines.extend(["", "## Concepts"])
    lines.extend(
        f"- [[concepts/{entry.document_key}|{entry.title}]] - type: concept"
        for entry in sorted(concepts, key=lambda item: item.document_key)
    )
    lines.extend(["", "## Sources"])
    lines.extend(f"- [[{path.removesuffix('.md')}|{title}]]" for path, title in source_entries)
    lines.append("")
    return "\n".join(lines)


def render_source_manifest_markdown(
    *,
    source_title: str,
    source_url: str | None,
    source_summary: str,
    source_tags: Sequence[str],
    content_hash: str,
    ingested_at: str,
    entity_links: Sequence[tuple[str, str]],
    concept_links: Sequence[tuple[str, str]],
) -> str:
    """원본 클리핑 한 건의 요약과 생성된 지식 문서를 연결한다."""
    original = source_url or source_title
    return (
        "---\n"
        "type: source\n"
        f"created: {_yaml(ingested_at[:10])}\n"
        f"updated: {_yaml(ingested_at[:10])}\n"
        f"source_file: {_yaml(original)}\n"
        f"tags: {_yaml(_unique(source_tags))}\n"
        "aliases: []\n"
        f"contentHash: {_yaml(content_hash)}\n"
        "generation_complete: true\n"
        "---\n"
        "## Source\n"
        f"- Original: {original}\n"
        f"- Ingested: {ingested_at}\n"
        "## Core Content\n"
        f"{source_summary or '(요약 없음)'}\n"
        "## Key Entities\n"
        f"{_bullet_block((f'[[entities/{key}|{title}]]' for key, title in entity_links), '(No entities)')}\n"
        "## Key Concepts\n"
        f"{_bullet_block((f'[[concepts/{key}|{title}]]' for key, title in concept_links), '(No concepts)')}\n"
    )


def render_log_entry(
    *,
    timestamp: str,
    source_title: str,
    model: str,
    source_size_bytes: int,
    created_paths: Sequence[str],
    updated_paths: Sequence[str],
) -> str:
    """이번 ingest의 생성·갱신 결과를 Wiki 운영 로그 Block으로 만든다."""
    created = ", ".join(f"[[{path.removesuffix('.md')}]]" for path in created_paths)
    updated = ", ".join(f"[[{path.removesuffix('.md')}]]" for path in updated_paths)
    size_kb = source_size_bytes / 1024
    return (
        f"## [{timestamp}] ingest | {source_title} · {model} · {size_kb:.1f}KB\n\n"
        f"**Created pages**：{created}\n\n"
        f"**Updated pages**：{updated}\n"
    )
