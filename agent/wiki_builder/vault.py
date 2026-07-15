"""LLM Wiki Vault Markdown 렌더링.

LLM 호출이나 DB 접근 없이, 이미 결정된 entity/concept/schema/index/sources/log
내용을 Agent DB Wiki 생성 규칙서의 템플릿에 맞춰 Markdown 문자열로만 조립한다.
문서 key·경로 계산과 content_hash 계산도 이 모듈이 담당해 planner와 persistence가
같은 규칙을 공유한다.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence

from agent.wiki_builder.models import ExistingWikiEntry, WikiRelationPlan

SCHEMA_DOCUMENT_KEY = "schema"
SCHEMA_FILE_PATH = "schema/schema.md"

_SLUG_INVALID = re.compile(r"[^0-9A-Za-z가-힣]+")
_SLUG_COLLAPSE = re.compile(r"-{2,}")


def slugify(name: str) -> str:
    """entity·concept 이름을 document_key/파일명으로 쓸 수 있는 slug로 변환한다."""
    normalized = _SLUG_INVALID.sub("-", name.strip()).strip("-")
    normalized = _SLUG_COLLAPSE.sub("-", normalized).lower()
    if not normalized:
        raise ValueError(f"빈 이름은 document_key로 변환할 수 없습니다: {name!r}")
    return normalized


def compute_content_hash(content: str) -> str:
    """문서 본문의 64자 SHA-256 무결성 Hash를 계산한다."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def entity_file_path(document_key: str) -> str:
    """entity document_kind의 Vault 경로를 만든다."""
    return f"entities/{document_key}.md"


def concept_file_path(document_key: str) -> str:
    """concept document_kind의 Vault 경로를 만든다."""
    return f"concepts/{document_key}.md"


def _bullet_lines(items: Iterable[str]) -> list[str]:
    """문자열 목록을 Markdown Bullet 줄 목록으로 변환한다."""
    return [f"- {item}" for item in items]


def _bullet_block(items: Iterable[str], empty_text: str) -> str:
    """Bullet 목록을 한 Block 문자열로 합치고, 비어 있으면 안내 문구를 반환한다."""
    lines = _bullet_lines(items)
    return "\n".join(lines) if lines else f"- {empty_text}"


def render_entity_markdown(
    *,
    name: str,
    domain: str,
    role: str,
    columns: Sequence[str],
    relations: Sequence[str],
    related_concepts: Sequence[str],
    source_titles: Sequence[str],
) -> str:
    """규칙서 entities/ 템플릿에 맞춰 entity 문서 Markdown을 만든다."""
    return (
        "---\n"
        f'title: "{name}"\n'
        "type: entity\n"
        f"domain: {domain}\n"
        f"tags: [entity, {domain}]\n"
        "---\n"
        f"# {name}\n"
        "## 역할\n"
        f"{role}\n"
        "## 주요 컬럼\n"
        f"{_bullet_block(columns, '기록된 컬럼 없음')}\n"
        "## 관계\n"
        f"{_bullet_block(relations, '기록된 관계 없음')}\n"
        "## 관련 개념\n"
        f"{_bullet_block((f'[[{slugify(c)}]] {c}' for c in related_concepts), '관련 개념 없음')}\n"
        "## 출처\n"
        f"{_bullet_block((f'[[{slugify(s)}]] {s}' for s in source_titles), '출처 없음')}\n"
    )


def render_concept_markdown(
    *,
    title: str,
    summary: str,
    explanation: str,
    related_entities: Sequence[str],
    related_concepts: Sequence[str],
    source_titles: Sequence[str],
) -> str:
    """규칙서 concepts/ 템플릿에 맞춰 concept 문서 Markdown을 만든다."""
    return (
        "---\n"
        f'title: "{title}"\n'
        "type: concept\n"
        "tags: [concept]\n"
        "---\n"
        f"# {title}\n"
        f"> {summary}\n"
        "## 설명 (왜 이렇게 설계했는지, 트레이드오프)\n"
        f"{explanation}\n"
        "## 관련 엔티티\n"
        f"{_bullet_block((f'[[{slugify(e)}]] {e}' for e in related_entities), '관련 엔티티 없음')}\n"
        "## 관련 개념\n"
        f"{_bullet_block((f'[[{slugify(c)}]] {c}' for c in related_concepts), '관련 개념 없음')}\n"
        "## 출처\n"
        f"{_bullet_block((f'[[{slugify(s)}]] {s}' for s in source_titles), '출처 없음')}\n"
    )


def render_schema_markdown(
    *,
    entities: Sequence[ExistingWikiEntry],
    concepts: Sequence[ExistingWikiEntry],
    relations: Sequence[WikiRelationPlan],
) -> str:
    """Namespace의 최신 entity·concept·관계 전체로 schema/schema.md를 다시 만든다."""
    lines = [
        "---",
        'title: "Schema"',
        "type: schema",
        "tags: [schema]",
        "---",
        "# Schema",
        "",
        "## Entities",
    ]
    if entities:
        by_domain: dict[str, list[ExistingWikiEntry]] = {}
        for entry in entities:
            by_domain.setdefault(entry.domain or "미분류", []).append(entry)
        for domain in sorted(by_domain):
            lines.append(f"### {domain}")
            lines.extend(
                _bullet_lines(
                    f"[[{entry.document_key}]] {entry.title}"
                    for entry in sorted(by_domain[domain], key=lambda e: e.document_key)
                )
            )
    else:
        lines.append("- (등록된 entity 없음)")
    lines.append("")
    lines.append("## Concepts")
    if concepts:
        lines.extend(
            _bullet_lines(
                f"[[{entry.document_key}]] {entry.title}"
                for entry in sorted(concepts, key=lambda e: e.document_key)
            )
        )
    else:
        lines.append("- (등록된 concept 없음)")
    lines.append("")
    lines.append("## Relations")
    if relations:
        lines.extend(
            _bullet_lines(
                f"[[{relation.source_document_key}]] --{relation.relation_type}--> "
                f"[[{relation.target_document_key}]]"
                for relation in relations
            )
        )
    else:
        lines.append("- (등록된 관계 없음)")
    lines.append("")
    return "\n".join(lines)


def render_index_markdown(
    *,
    entities: Sequence[ExistingWikiEntry],
    concepts: Sequence[ExistingWikiEntry],
    source_titles: Sequence[str],
    generated_at: str,
) -> str:
    """entities/concepts/schema/sources 최신 목록으로 index.md 전체를 다시 만든다."""
    lines = [
        "# Wiki Index",
        "",
        f"_generated_at: {generated_at}_",
        "",
        f"## Entities ({len(entities)})",
    ]
    lines.extend(
        _bullet_lines(
            f"[[{entry.document_key}]] {entry.title}"
            for entry in sorted(entities, key=lambda e: e.document_key)
        )
        or ["- (등록된 entity 없음)"]
    )
    lines.append("")
    lines.append(f"## Concepts ({len(concepts)})")
    lines.extend(
        _bullet_lines(
            f"[[{entry.document_key}]] {entry.title}"
            for entry in sorted(concepts, key=lambda e: e.document_key)
        )
        or ["- (등록된 concept 없음)"]
    )
    lines.append("")
    lines.append("## Schema")
    lines.append(f"- [[{SCHEMA_DOCUMENT_KEY}]]")
    lines.append("")
    lines.append(f"## Sources ({len(source_titles)})")
    lines.extend(
        _bullet_lines(f"[[{slugify(title)}]] {title}" for title in source_titles)
        or ["- (등록된 source 없음)"]
    )
    lines.append("")
    return "\n".join(lines)


def render_source_manifest_markdown(
    *,
    source_title: str,
    source_url: str | None,
    entity_titles: Sequence[str],
    concept_titles: Sequence[str],
) -> str:
    """이 원본이 생성·갱신한 entity·concept을 추적하는 sources/ 산출물을 만든다."""
    lines = [
        "---",
        f'title: "{source_title}"',
        "type: source",
        "tags: [source]",
        "---",
        f"# {source_title}",
    ]
    if source_url:
        lines.append(f"- 원본: {source_url}")
    lines.append("## 이 출처로 생성·갱신된 Entity")
    lines.extend(
        _bullet_lines(f"[[{slugify(title)}]] {title}" for title in entity_titles)
        or ["- (없음)"]
    )
    lines.append("## 이 출처로 생성·갱신된 Concept")
    lines.extend(
        _bullet_lines(f"[[{slugify(title)}]] {title}" for title in concept_titles)
        or ["- (없음)"]
    )
    lines.append("")
    return "\n".join(lines)


def render_log_entry(
    *,
    timestamp: str,
    source_title: str,
    created_entities: Sequence[str],
    updated_entities: Sequence[str],
    created_concepts: Sequence[str],
    updated_concepts: Sequence[str],
    schema_regenerated: bool,
) -> str:
    """이번 Build 한 번을 요약하는 log 한 줄을 만든다."""
    parts = [f"{timestamp} | 출처: {source_title}"]
    if created_entities:
        parts.append(f"entity 생성: {', '.join(created_entities)}")
    if updated_entities:
        parts.append(f"entity 갱신: {', '.join(updated_entities)}")
    if created_concepts:
        parts.append(f"concept 생성: {', '.join(created_concepts)}")
    if updated_concepts:
        parts.append(f"concept 갱신: {', '.join(updated_concepts)}")
    parts.append(f"schema 재생성: {'예' if schema_regenerated else '아니오'}")
    return " | ".join(parts)
