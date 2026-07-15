-- 사용자 원본 자료와 Agent가 생성한 LLM Wiki를 서로 다른 생명주기로 분리한다.

\set ON_ERROR_STOP on

BEGIN;

-- 클리핑·URL 저장 등 사용자가 제공한 원본 자료의 논리 문서를 보관한다.
CREATE TABLE agent.user_source_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL,
    namespace_key text NOT NULL,
    source_type text NOT NULL
        CHECK (source_type IN ('web_clipping', 'url', 'content_mark', 'content_save', 'memo', 'edit', 'conversation')),
    canonical_url text,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'deleted', 'archived', 'superseded')),
    current_version integer NOT NULL DEFAULT 1 CHECK (current_version > 0),
    content_hash text NOT NULL CHECK (length(content_hash) = 64),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    deleted_at timestamptz,
    UNIQUE (id, namespace_key),
    CHECK (namespace_key = 'user/' || user_id)
);

CREATE UNIQUE INDEX uq_user_source_documents_content
    ON agent.user_source_documents (namespace_key, content_hash)
    WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_user_source_documents_url
    ON agent.user_source_documents (namespace_key, canonical_url)
    WHERE canonical_url IS NOT NULL AND deleted_at IS NULL;
CREATE INDEX ix_user_source_documents_scope_updated
    ON agent.user_source_documents (namespace_key, updated_at DESC)
    WHERE deleted_at IS NULL;

-- 원본의 Frontmatter와 Markdown 본문을 변경 이력 단위로 보존한다.
CREATE TABLE agent.user_source_document_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_document_id uuid NOT NULL,
    namespace_key text NOT NULL,
    source_event_id uuid REFERENCES agent.wiki_source_events(id),
    version integer NOT NULL CHECK (version > 0),
    title text NOT NULL,
    author text,
    published_at timestamptz,
    clipped_on date,
    description text,
    tags text[] NOT NULL DEFAULT '{}',
    raw_content text,
    content_format text NOT NULL DEFAULT 'markdown'
        CHECK (content_format IN ('markdown', 'plain_text', 'html', 'pdf', 'external_object')),
    content_hash text NOT NULL CHECK (length(content_hash) = 64),
    object_uri text,
    source_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (source_document_id, version),
    UNIQUE (id, namespace_key),
    FOREIGN KEY (source_document_id, namespace_key)
        REFERENCES agent.user_source_documents(id, namespace_key) ON DELETE CASCADE,
    CHECK (raw_content IS NOT NULL OR object_uri IS NOT NULL)
);

CREATE INDEX ix_user_source_document_versions_tags
    ON agent.user_source_document_versions USING gin (tags);
CREATE INDEX ix_user_source_document_versions_clipped
    ON agent.user_source_document_versions (namespace_key, clipped_on DESC)
    WHERE clipped_on IS NOT NULL;

-- 하나의 LLM Wiki Version이 참고한 하나 이상의 원본 Version을 기록한다.
CREATE TABLE agent.wiki_document_sources (
    wiki_document_version_id uuid NOT NULL,
    source_document_version_id uuid NOT NULL,
    namespace_key text NOT NULL,
    relation_type text NOT NULL DEFAULT 'source'
        CHECK (relation_type IN ('source', 'citation', 'inspiration')),
    relevance_score numeric(8, 6)
        CHECK (relevance_score IS NULL OR relevance_score BETWEEN 0 AND 1),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (wiki_document_version_id, source_document_version_id),
    FOREIGN KEY (wiki_document_version_id, namespace_key)
        REFERENCES agent.wiki_document_versions(id, namespace_key) ON DELETE CASCADE,
    FOREIGN KEY (source_document_version_id, namespace_key)
        REFERENCES agent.user_source_document_versions(id, namespace_key) ON DELETE CASCADE
);

CREATE INDEX ix_wiki_document_sources_source
    ON agent.wiki_document_sources (source_document_version_id, wiki_document_version_id);

-- 0003에서 Wiki로 잘못 분류했던 개인 웹 클리핑을 원본 문서로 옮긴다.
INSERT INTO agent.user_source_documents (
    id,
    user_id,
    namespace_key,
    source_type,
    canonical_url,
    status,
    current_version,
    content_hash,
    metadata,
    created_at,
    updated_at,
    deleted_at
)
SELECT
    id,
    user_id,
    namespace_key,
    source_type,
    canonical_url,
    status,
    current_version,
    content_hash,
    metadata,
    created_at,
    updated_at,
    deleted_at
FROM agent.wiki_documents
WHERE knowledge_scope = 'personal'
  AND source_type = 'web_clipping';

INSERT INTO agent.user_source_document_versions (
    id,
    source_document_id,
    namespace_key,
    source_event_id,
    version,
    title,
    author,
    published_at,
    clipped_on,
    description,
    tags,
    raw_content,
    content_format,
    content_hash,
    object_uri,
    source_metadata,
    created_at
)
SELECT
    version.id,
    version.document_id,
    version.namespace_key,
    document.source_event_id,
    version.version,
    version.title,
    version.author,
    version.published_at,
    version.clipped_on,
    version.description,
    version.tags,
    version.normalized_content,
    version.content_format,
    version.content_hash,
    version.object_uri,
    version.source_metadata,
    version.created_at
FROM agent.wiki_document_versions AS version
JOIN agent.wiki_documents AS document
  ON document.id = version.document_id
WHERE document.knowledge_scope = 'personal'
  AND document.source_type = 'web_clipping';

-- 아직 대기 중인 Wiki Build Job이 새 원본 식별자를 사용하도록 계약을 이관한다.
UPDATE agent.agent_jobs AS job
SET payload = (job.payload - 'document_id' - 'document_version_id')
    || jsonb_build_object(
        'source_document_id', job.payload ->> 'document_id',
        'source_document_version_id', job.payload ->> 'document_version_id'
    )
WHERE job.job_type = 'personal_wiki_build'
  AND job.payload ? 'document_id'
  AND job.payload ? 'document_version_id'
  AND EXISTS (
      SELECT 1
      FROM agent.user_source_document_versions AS source_version
      WHERE source_version.id::text = job.payload ->> 'document_version_id'
  );

UPDATE agent.wiki_source_events AS event
SET payload = (event.payload - 'document_id' - 'document_version_id')
    || jsonb_build_object(
        'source_document_id', event.payload ->> 'document_id',
        'source_document_version_id', event.payload ->> 'document_version_id'
    )
WHERE event.payload ? 'document_id'
  AND event.payload ? 'document_version_id'
  AND EXISTS (
      SELECT 1
      FROM agent.user_source_document_versions AS source_version
      WHERE source_version.source_event_id = event.id
        AND source_version.id::text = event.payload ->> 'document_version_id'
  );

-- 잘못 분류된 Wiki 행을 제거하기 전에 참조 무결성을 안전하게 정리한다.
UPDATE agent.interest_evidence AS evidence
SET document_id = NULL,
    source_event_id = COALESCE(evidence.source_event_id, document.source_event_id)
FROM agent.wiki_documents AS document
WHERE evidence.document_id = document.id
  AND document.knowledge_scope = 'personal'
  AND document.source_type = 'web_clipping'
  AND COALESCE(evidence.source_event_id, document.source_event_id) IS NOT NULL;

DELETE FROM agent.interest_evidence AS evidence
USING agent.wiki_documents AS document
WHERE evidence.document_id = document.id
  AND document.knowledge_scope = 'personal'
  AND document.source_type = 'web_clipping';

DELETE FROM agent.global_trend_documents AS link
USING agent.wiki_documents AS document
WHERE link.document_id = document.id
  AND document.knowledge_scope = 'personal'
  AND document.source_type = 'web_clipping';

UPDATE agent.discovery_candidates AS candidate
SET document_id = NULL
FROM agent.wiki_documents AS document
WHERE candidate.document_id = document.id
  AND document.knowledge_scope = 'personal'
  AND document.source_type = 'web_clipping'
  AND candidate.trend_id IS NOT NULL;

DELETE FROM agent.discovery_candidates AS candidate
USING agent.wiki_documents AS document
WHERE candidate.document_id = document.id
  AND document.knowledge_scope = 'personal'
  AND document.source_type = 'web_clipping';

UPDATE agent.citations AS citation
SET document_version_id = NULL,
    chunk_id = NULL,
    url = COALESCE(citation.url, moved.canonical_url)
FROM (
    SELECT
        version.id AS version_id,
        chunk.id AS chunk_id,
        document.canonical_url
    FROM agent.wiki_document_versions AS version
    JOIN agent.wiki_documents AS document
      ON document.id = version.document_id
    LEFT JOIN agent.wiki_chunks AS chunk
      ON chunk.document_version_id = version.id
    WHERE document.knowledge_scope = 'personal'
      AND document.source_type = 'web_clipping'
) AS moved
WHERE (citation.document_version_id = moved.version_id OR citation.chunk_id = moved.chunk_id)
  AND COALESCE(citation.url, moved.canonical_url) IS NOT NULL;

DELETE FROM agent.citations AS citation
WHERE citation.document_version_id IN (
    SELECT version.id
    FROM agent.wiki_document_versions AS version
    JOIN agent.wiki_documents AS document
      ON document.id = version.document_id
    WHERE document.knowledge_scope = 'personal'
      AND document.source_type = 'web_clipping'
)
OR citation.chunk_id IN (
    SELECT chunk.id
    FROM agent.wiki_chunks AS chunk
    JOIN agent.wiki_document_versions AS version
      ON version.id = chunk.document_version_id
    JOIN agent.wiki_documents AS document
      ON document.id = version.document_id
    WHERE document.knowledge_scope = 'personal'
      AND document.source_type = 'web_clipping'
);

DELETE FROM agent.wiki_documents
WHERE knowledge_scope = 'personal'
  AND source_type = 'web_clipping';

-- Wiki Version에는 Agent가 생성한 결과 본문과 요약만 남긴다.
DROP INDEX agent.ix_wiki_document_versions_tags;
DROP INDEX agent.ix_wiki_document_versions_clipped;

ALTER TABLE agent.wiki_document_versions
    DROP CONSTRAINT wiki_document_versions_content_format_check,
    DROP COLUMN author,
    DROP COLUMN published_at,
    DROP COLUMN clipped_on,
    DROP COLUMN description,
    DROP COLUMN tags,
    DROP COLUMN content_format;

ALTER TABLE agent.user_source_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.user_source_document_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.wiki_document_sources ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_source_document_isolation ON agent.user_source_documents
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());
CREATE POLICY user_source_version_isolation ON agent.user_source_document_versions
    USING (agent.has_system_scope() OR namespace_key = 'user/' || agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR namespace_key = 'user/' || agent.current_user_id());
CREATE POLICY wiki_document_source_isolation ON agent.wiki_document_sources
    USING (agent.has_system_scope() OR namespace_key = 'user/' || agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR namespace_key = 'user/' || agent.current_user_id());

CREATE TRIGGER set_user_source_documents_updated_at
    BEFORE UPDATE ON agent.user_source_documents
    FOR EACH ROW EXECUTE FUNCTION agent.set_updated_at();

INSERT INTO agent.schema_migrations (version, description)
VALUES (4, 'Separate user source documents from generated LLM Wiki');

COMMIT;
