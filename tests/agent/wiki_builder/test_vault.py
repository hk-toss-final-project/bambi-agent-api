"""agent/wiki_builder/vault.py의 순수 Markdown 렌더링을 검증한다. LLM·DB 호출 없음."""

import pytest

from agent.wiki_builder import vault
from agent.wiki_builder.models import ExistingWikiEntry, WikiRelationPlan


def test_slugify_normalizes_spaces_and_case() -> None:
    """공백과 대소문자를 정리해 안정적인 document_key를 만든다."""
    assert vault.slugify("  Vector Search  ") == "vector-search"
    assert vault.slugify("사용자 인증") == "사용자-인증"


def test_slugify_collapses_repeated_separators() -> None:
    """연속된 구분자를 하나로 합친다."""
    assert vault.slugify("A///B  --  C") == "a-b-c"


def test_slugify_rejects_empty_name() -> None:
    """빈 이름은 document_key로 변환할 수 없다."""
    with pytest.raises(ValueError):
        vault.slugify("   ")


def test_compute_content_hash_is_deterministic_and_64_chars() -> None:
    """같은 입력은 같은 64자 Hash를 만들고, 다른 입력은 다른 Hash를 만든다."""
    first = vault.compute_content_hash("본문")
    again = vault.compute_content_hash("본문")
    different = vault.compute_content_hash("다른 본문")

    assert first == again
    assert len(first) == 64
    assert first != different


def test_entity_and_concept_file_paths_match_db_check_constraint() -> None:
    """wiki_documents의 file_path CHECK 패턴과 일치하는 경로를 만든다."""
    assert vault.entity_file_path("wiki-documents") == "entities/wiki-documents.md"
    assert vault.concept_file_path("versioned-config") == "concepts/versioned-config.md"
    assert vault.SCHEMA_FILE_PATH == "schema/schema.md"


def test_render_entity_markdown_matches_rulebook_template() -> None:
    """규칙서 entities/ 템플릿의 Frontmatter와 6개 Heading을 그대로 포함한다."""
    markdown = vault.render_entity_markdown(
        name="wiki_documents",
        domain="지식 문서",
        role="Personal LLM Wiki 문서의 Head를 관리한다.",
        columns=["id", "document_kind", "document_key"],
        relations=["wiki_document_versions와 1:N"],
        related_concepts=["Versioned Configuration"],
        source_titles=["Agent DB 테이블 카탈로그"],
    )

    assert markdown.startswith("---\n")
    assert 'title: "wiki_documents"' in markdown
    assert "type: entity" in markdown
    assert "domain: 지식 문서" in markdown
    assert "# wiki_documents" in markdown
    assert "## 역할" in markdown
    assert "## 주요 컬럼" in markdown
    assert "- id" in markdown
    assert "## 관계" in markdown
    assert "## 관련 개념" in markdown
    assert "[[versioned-configuration]] Versioned Configuration" in markdown
    assert "## 출처" in markdown
    assert "[[agent-db-테이블-카탈로그]] Agent DB 테이블 카탈로그" in markdown


def test_render_entity_markdown_fills_empty_sections_with_placeholder() -> None:
    """값이 없는 목록 Section은 안내 문구로 채운다."""
    markdown = vault.render_entity_markdown(
        name="빈 엔티티",
        domain="미분류",
        role="설명 없음",
        columns=[],
        relations=[],
        related_concepts=[],
        source_titles=[],
    )

    assert "- 기록된 컬럼 없음" in markdown
    assert "- 기록된 관계 없음" in markdown
    assert "- 관련 개념 없음" in markdown
    assert "- 출처 없음" in markdown


def test_render_concept_markdown_matches_rulebook_template() -> None:
    """규칙서 concepts/ 템플릿의 요약 인용문과 Heading을 포함한다."""
    markdown = vault.render_concept_markdown(
        title="Versioned Configuration",
        summary="설정을 덮어쓰지 않고 새 Version Row로 추가한다.",
        explanation="이전 값 복구와 감사 추적을 위해 불변 이력을 유지한다.",
        related_entities=["prompt_templates", "model_configs"],
        related_concepts=[],
        source_titles=["Agent DB 상세 설계"],
    )

    assert 'title: "Versioned Configuration"' in markdown
    assert "type: concept" in markdown
    assert "# Versioned Configuration" in markdown
    assert "> 설정을 덮어쓰지 않고 새 Version Row로 추가한다." in markdown
    assert "## 설명 (왜 이렇게 설계했는지, 트레이드오프)" in markdown
    assert "## 관련 엔티티" in markdown
    assert "[[prompt-templates]] prompt_templates" in markdown
    assert "## 관련 개념" in markdown
    assert "- 관련 개념 없음" in markdown
    assert "## 출처" in markdown


def test_render_schema_markdown_groups_entities_by_domain() -> None:
    """entity를 domain별로 묶고 concept·relation을 함께 나열한다."""
    entities = [
        ExistingWikiEntry("entity", "wiki-documents", "wiki_documents", "지식 문서", None),
        ExistingWikiEntry("entity", "prompt-templates", "prompt_templates", "설정", None),
    ]
    concepts = [ExistingWikiEntry("concept", "versioned-configuration", "Versioned Configuration", None, None)]
    relations = [
        WikiRelationPlan(
            source_document_key="wiki-documents",
            source_document_kind="entity",
            target_document_key="versioned-configuration",
            target_document_kind="concept",
            relation_type="applies_concept",
        )
    ]

    markdown = vault.render_schema_markdown(entities=entities, concepts=concepts, relations=relations)

    assert "type: schema" in markdown
    assert "### 지식 문서" in markdown
    assert "### 설정" in markdown
    assert "[[wiki-documents]] wiki_documents" in markdown
    assert "## Concepts" in markdown
    assert "[[versioned-configuration]] Versioned Configuration" in markdown
    assert "## Relations" in markdown
    assert "[[wiki-documents]] --applies_concept--> [[versioned-configuration]]" in markdown


def test_render_schema_markdown_handles_empty_namespace() -> None:
    """entity·concept·relation이 하나도 없어도 안내 문구로 채운다."""
    markdown = vault.render_schema_markdown(entities=[], concepts=[], relations=[])

    assert "- (등록된 entity 없음)" in markdown
    assert "- (등록된 concept 없음)" in markdown
    assert "- (등록된 관계 없음)" in markdown


def test_render_index_markdown_lists_all_sections() -> None:
    """index.md는 entity·concept·schema·source를 모두 나열한다."""
    entities = [ExistingWikiEntry("entity", "wiki-documents", "wiki_documents", "지식 문서", None)]
    concepts = [ExistingWikiEntry("concept", "versioned-configuration", "Versioned Configuration", None, None)]

    markdown = vault.render_index_markdown(
        entities=entities,
        concepts=concepts,
        source_titles=["클리핑: pgvector 소개"],
        generated_at="2026-07-15T00:00:00+09:00",
    )

    assert "# Wiki Index" in markdown
    assert "_generated_at: 2026-07-15T00:00:00+09:00_" in markdown
    assert "## Entities (1)" in markdown
    assert "[[wiki-documents]] wiki_documents" in markdown
    assert "## Concepts (1)" in markdown
    assert "## Schema" in markdown
    assert "- [[schema]]" in markdown
    assert "## Sources (1)" in markdown
    assert "클리핑: pgvector 소개" in markdown


def test_render_source_manifest_lists_produced_documents() -> None:
    """이 원본이 만든 entity·concept을 함께 보여준다."""
    markdown = vault.render_source_manifest_markdown(
        source_title="클리핑: pgvector 소개",
        source_url="https://example.com/pgvector",
        entity_titles=["wiki_embeddings"],
        concept_titles=[],
    )

    assert 'title: "클리핑: pgvector 소개"' in markdown
    assert "- 원본: https://example.com/pgvector" in markdown
    assert "[[wiki-embeddings]] wiki_embeddings" in markdown
    assert "## 이 출처로 생성·갱신된 Concept" in markdown
    assert "- (없음)" in markdown


def test_render_log_entry_summarizes_build_counts() -> None:
    """생성·갱신 개수와 schema 재생성 여부를 한 줄로 요약한다."""
    entry = vault.render_log_entry(
        timestamp="2026-07-15T00:00:00+09:00",
        source_title="클리핑: pgvector 소개",
        created_entities=["wiki_embeddings"],
        updated_entities=[],
        created_concepts=[],
        updated_concepts=["Versioned Configuration"],
        schema_regenerated=True,
    )

    assert entry.startswith("2026-07-15T00:00:00+09:00 | 출처: 클리핑: pgvector 소개")
    assert "entity 생성: wiki_embeddings" in entry
    assert "concept 갱신: Versioned Configuration" in entry
    assert "schema 재생성: 예" in entry
    assert "entity 갱신" not in entry
