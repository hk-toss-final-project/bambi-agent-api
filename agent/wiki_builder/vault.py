"""개인 지식 Wiki Vault 렌더러의 호환 용 Facade."""

from .features.vault import (
    SCHEMA_DOCUMENT_KEY,
    SCHEMA_FILE_PATH,
    compute_content_hash,
    concept_file_path,
    entity_file_path,
    render_concept_markdown,
    render_entity_markdown,
    render_index_markdown,
    render_log_entry,
    render_schema_markdown,
    render_source_manifest_markdown,
    slugify,
    source_file_path,
)

__all__ = [
    "SCHEMA_DOCUMENT_KEY",
    "SCHEMA_FILE_PATH",
    "compute_content_hash",
    "concept_file_path",
    "entity_file_path",
    "render_concept_markdown",
    "render_entity_markdown",
    "render_index_markdown",
    "render_log_entry",
    "render_schema_markdown",
    "render_source_manifest_markdown",
    "slugify",
    "source_file_path",
]
