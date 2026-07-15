"""개인 지식 Wiki Vault Markdown 렌더러를 검증한다."""

import pytest

from agent.wiki_builder.features import vault
from agent.wiki_builder.models import ExistingWikiEntry, WikiRelationPlan


def test_slugify_normalizes_spaces_and_case() -> None:
    """공백과 대소문자를 정리해 안정적인 document_key를 만든다."""
    assert vault.slugify("  Vector Search  ") == "vector-search"
    assert vault.slugify("사용자 인증") == "사용자-인증"


def test_slugify_preserves_original_script_and_emoji() -> None:
    """일본어·중국어와 Emoji를 번역하거나 제거하지 않고 파일 키에 보존한다."""
    assert vault.slugify("札幌 夏旅行 🪻") == "札幌-夏旅行-🪻"


def test_slugify_rejects_empty_name() -> None:
    """빈 이름은 document_key로 변환할 수 없다."""
    with pytest.raises(ValueError):
        vault.slugify("   ")


def test_compute_content_hash_is_deterministic() -> None:
    """내용 Hash는 결정적이고 64자이다."""
    first = vault.compute_content_hash("본문")
    assert first == vault.compute_content_hash("본문")
    assert len(first) == 64


def test_paths_match_database_contract() -> None:
    """entity·concept·schema 경로와 Schema 키가 DB 제약에 맞다."""
    assert vault.entity_file_path("obsidian") == "entities/obsidian.md"
    assert vault.concept_file_path("연결-노트") == "concepts/연결-노트.md"
    assert vault.SCHEMA_DOCUMENT_KEY == "root"
    assert vault.SCHEMA_FILE_PATH == "schema/schema.md"
    assert vault.source_file_path("검색결과", "abcdef1234") == "sources/검색결과_abcdef.md"


def test_render_entity_markdown_matches_personal_vault_template() -> None:
    """entity Markdown이 Frontmatter와 고정 섹션을 모두 포함한다."""
    markdown = vault.render_entity_markdown(
        name="Obsidian",
        subtype="product",
        description="Markdown 기반 지식 관리 도구다.",
        aliases=["옵시디언"],
        related_entities=["Obsidian Web Clipper"],
        related_concepts=["연결 노트"],
        mention_entries=[
            ("Markdown 파일을 사용한다.", "[[sources/obsidian_abcdef|Obsidian 소개]]")
        ],
        source_links=[],
        source_title="Obsidian 소개",
        source_link="[[sources/obsidian_abcdef|Obsidian 소개]]",
        created="2026-07-15",
        updated="2026-07-15",
    )

    assert "type: entity" in markdown
    assert 'tags: ["product"]' in markdown
    assert 'aliases: ["옵시디언"]' in markdown
    assert "generation_complete: true" in markdown
    assert "## Basic Information" in markdown
    assert "## Description" in markdown
    assert "[[entities/obsidian-web-clipper|Obsidian Web Clipper]]" in markdown
    assert "[[concepts/연결-노트|연결 노트]]" in markdown
    assert '"Markdown 파일을 사용한다." — [[sources/obsidian_abcdef|Obsidian 소개]]' in markdown


def test_render_concept_markdown_matches_personal_vault_template() -> None:
    """concept Markdown이 정의·특성·활용·관계·인용 섹션을 포함한다."""
    markdown = vault.render_concept_markdown(
        title="연결 노트",
        subtype="method",
        definition="노트를 링크로 연결하는 방법이다.",
        key_characteristics=["양방향 연결"],
        applications=["개인 지식 관리"],
        aliases=["linked notes"],
        related_entities=["Obsidian"],
        related_concepts=["지식 그래프"],
        mention_entries=[
            ("노트를 연결한다.", "[[sources/obsidian_abcdef|Obsidian 소개]]")
        ],
        source_links=[],
        source_link="[[sources/obsidian_abcdef|Obsidian 소개]]",
        created="2026-07-15",
        updated="2026-07-15",
    )

    assert "type: concept" in markdown
    assert 'tags: ["method"]' in markdown
    assert "## Definition" in markdown
    assert "## Key Characteristics" in markdown
    assert "- 양방향 연결" in markdown
    assert "## Applications" in markdown
    assert "[[entities/obsidian|Obsidian]]" in markdown


def test_render_schema_markdown_uses_full_paths() -> None:
    """Schema의 문서 링크가 entity·concept 풀 경로를 사용한다."""
    entities = [
        ExistingWikiEntry("entity", "obsidian", "Obsidian", "product", None)
    ]
    concepts = [
        ExistingWikiEntry("concept", "연결-노트", "연결 노트", "method", None)
    ]
    relations = [
        WikiRelationPlan(
            "obsidian", "entity", "연결-노트", "concept", "applies_concept"
        )
    ]

    markdown = vault.render_schema_markdown(
        entities=entities, concepts=concepts, relations=relations
    )

    assert "[[entities/obsidian|Obsidian]]" in markdown
    assert "[[concepts/연결-노트|연결 노트]]" in markdown
    assert "[[entities/obsidian]] --applies_concept--> [[concepts/연결-노트]]" in markdown


def test_render_source_manifest_inherits_source_tags() -> None:
    """source Markdown은 클리핑 태그와 내용 Hash를 그대로 보존한다."""
    markdown = vault.render_source_manifest_markdown(
        source_title="Obsidian 소개",
        source_url="https://example.com/obsidian",
        source_summary="Obsidian은 지식 관리 도구다.",
        source_tags=["clippings", "pkm"],
        content_hash="abcdef",
        ingested_at="2026-07-15T12:00:00+09:00",
        entity_links=[("obsidian", "Obsidian")],
        concept_links=[("연결-노트", "연결 노트")],
    )

    assert 'tags: ["clippings", "pkm"]' in markdown
    assert 'contentHash: "abcdef"' in markdown
    assert "[[entities/obsidian|Obsidian]]" in markdown
    assert "[[concepts/연결-노트|연결 노트]]" in markdown


def test_render_log_entry_uses_operation_block() -> None:
    """ingest 로그를 한 줄이 아닌 운영 Block 형식으로 만든다."""
    entry = vault.render_log_entry(
        timestamp="2026-07-15T12:00:00+09:00",
        source_title="Obsidian 소개",
        model="gpt-4.1-mini",
        source_size_bytes=2048,
        created_paths=["entities/obsidian.md"],
        updated_paths=["schema/schema.md"],
    )

    assert "ingest | Obsidian 소개 · gpt-4.1-mini · 2.0KB" in entry
    assert "**Created pages**：[[entities/obsidian]]" in entry
    assert "**Updated pages**：[[schema/schema]]" in entry
