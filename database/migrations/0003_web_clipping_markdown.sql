-- 웹 클리핑 Markdown의 Frontmatter와 본문 형식을 문서 Version에 명시적으로 저장한다.

\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE agent.wiki_document_versions
    ADD COLUMN author text,
    ADD COLUMN published_at timestamptz,
    ADD COLUMN clipped_on date,
    ADD COLUMN description text,
    ADD COLUMN tags text[] NOT NULL DEFAULT '{}',
    ADD COLUMN content_format text;

UPDATE agent.wiki_document_versions
SET content_format = CASE
    WHEN normalized_content IS NOT NULL THEN 'markdown'
    ELSE 'external_object'
END;

ALTER TABLE agent.wiki_document_versions
    ALTER COLUMN content_format SET DEFAULT 'markdown',
    ALTER COLUMN content_format SET NOT NULL,
    ADD CONSTRAINT wiki_document_versions_content_format_check
        CHECK (content_format IN ('markdown', 'plain_text', 'external_object'));

CREATE INDEX ix_wiki_document_versions_tags
    ON agent.wiki_document_versions USING gin (tags);

CREATE INDEX ix_wiki_document_versions_clipped
    ON agent.wiki_document_versions (namespace_key, clipped_on DESC)
    WHERE clipped_on IS NOT NULL;

INSERT INTO agent.schema_migrations (version, description)
VALUES (3, 'Store web clipping Markdown fields');

COMMIT;
