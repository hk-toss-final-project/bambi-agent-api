-- LLM Wiki 문서를 Entity, Concept, Schema 파일로 식별하고 관계와 Build 구성을 보존한다.

\set ON_ERROR_STOP on

BEGIN;

-- 기존 Wiki Head에 Obsidian Vault의 안정적인 논리 Key와 파일 경로를 추가한다.
ALTER TABLE agent.wiki_documents
    ADD COLUMN document_kind text,
    ADD COLUMN document_key text,
    ADD COLUMN file_path text,
    ADD COLUMN domain text;

-- 구조화 이전 문서는 UUID 기반 Legacy 경로로 이관해 기존 행을 손실 없이 유지한다.
UPDATE agent.wiki_documents
SET document_kind = 'document',
    document_key = 'legacy-' || id::text,
    file_path = 'documents/' || id::text || '.md';

ALTER TABLE agent.wiki_documents
    ALTER COLUMN document_kind SET NOT NULL,
    ALTER COLUMN document_key SET NOT NULL,
    ALTER COLUMN file_path SET NOT NULL,
    ADD CONSTRAINT wiki_documents_document_kind_check
        CHECK (document_kind IN ('document', 'entity', 'concept', 'schema')),
    ADD CONSTRAINT wiki_documents_document_key_check
        CHECK (btrim(document_key) <> ''),
    ADD CONSTRAINT wiki_documents_domain_check
        CHECK (domain IS NULL OR btrim(domain) <> ''),
    ADD CONSTRAINT wiki_documents_file_path_check
        CHECK (
            (document_kind = 'document' AND file_path ~ '^documents/[^/]+[.]md$')
            OR (document_kind = 'entity' AND file_path ~ '^entities/[^/]+[.]md$')
            OR (document_kind = 'concept' AND file_path ~ '^concepts/[^/]+[.]md$')
            OR (
                document_kind = 'schema'
                AND document_key = 'root'
                AND file_path = 'schema/schema.md'
            )
        );

CREATE UNIQUE INDEX uq_wiki_documents_logical_key
    ON agent.wiki_documents (namespace_key, document_kind, document_key)
    WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_wiki_documents_file_path
    ON agent.wiki_documents (namespace_key, file_path)
    WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_wiki_documents_schema_per_namespace
    ON agent.wiki_documents (namespace_key)
    WHERE document_kind = 'schema' AND deleted_at IS NULL;
CREATE INDEX ix_wiki_documents_kind_updated
    ON agent.wiki_documents (namespace_key, document_kind, updated_at DESC)
    WHERE deleted_at IS NULL;

-- 사용자 Wiki Build와 문서 Version의 Namespace를 복합 FK로 일치시킨다.
ALTER TABLE agent.wiki_versions
    ADD COLUMN namespace_key text;

UPDATE agent.wiki_versions
SET namespace_key = 'user/' || user_id;

ALTER TABLE agent.wiki_versions
    ALTER COLUMN namespace_key SET NOT NULL,
    ADD CONSTRAINT wiki_versions_namespace_check
        CHECK (namespace_key = 'user/' || user_id),
    ADD CONSTRAINT wiki_versions_id_namespace_key_key
        UNIQUE (id, namespace_key);

-- 현재 Wiki Graph에서 Entity와 Concept 등 논리 문서 사이의 관계를 저장한다.
CREATE TABLE agent.wiki_document_relations (
    source_document_id uuid NOT NULL,
    target_document_id uuid NOT NULL,
    namespace_key text NOT NULL,
    relation_type text NOT NULL
        CHECK (relation_type IN (
            'entity_relation',
            'applies_concept',
            'related_concept',
            'alias_of'
        )),
    metadata jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (source_document_id, target_document_id, relation_type),
    FOREIGN KEY (source_document_id, namespace_key)
        REFERENCES agent.wiki_documents(id, namespace_key) ON DELETE CASCADE,
    FOREIGN KEY (target_document_id, namespace_key)
        REFERENCES agent.wiki_documents(id, namespace_key) ON DELETE CASCADE,
    CHECK (source_document_id <> target_document_id)
);

CREATE INDEX ix_wiki_document_relations_target
    ON agent.wiki_document_relations (namespace_key, target_document_id, relation_type);

-- 특정 Wiki Build를 구성한 정확한 문서 Version과 당시 파일 경로를 고정한다.
CREATE TABLE agent.wiki_version_documents (
    wiki_version_id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    namespace_key text NOT NULL,
    file_path text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (wiki_version_id, document_version_id),
    UNIQUE (wiki_version_id, file_path),
    FOREIGN KEY (wiki_version_id, namespace_key)
        REFERENCES agent.wiki_versions(id, namespace_key) ON DELETE CASCADE,
    FOREIGN KEY (document_version_id, namespace_key)
        REFERENCES agent.wiki_document_versions(id, namespace_key) ON DELETE CASCADE,
    CHECK (
        file_path ~ '^[^/].*[.]md$'
        AND file_path !~ '(^|/)[.][.]?(/|$)'
    )
);

CREATE INDEX ix_wiki_version_documents_document
    ON agent.wiki_version_documents (namespace_key, document_version_id, wiki_version_id);

ALTER TABLE agent.wiki_document_relations ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.wiki_version_documents ENABLE ROW LEVEL SECURITY;

CREATE POLICY wiki_document_relation_read ON agent.wiki_document_relations
    FOR SELECT
    USING (
        namespace_key = 'global'
        OR agent.has_system_scope()
        OR namespace_key = 'user/' || agent.current_user_id()
    );
CREATE POLICY wiki_document_relation_write ON agent.wiki_document_relations
    FOR ALL
    USING (
        agent.has_system_scope()
        OR namespace_key = 'user/' || agent.current_user_id()
    )
    WITH CHECK (
        agent.has_system_scope()
        OR namespace_key = 'user/' || agent.current_user_id()
    );

CREATE POLICY wiki_version_document_isolation ON agent.wiki_version_documents
    USING (
        agent.has_system_scope()
        OR namespace_key = 'user/' || agent.current_user_id()
    )
    WITH CHECK (
        agent.has_system_scope()
        OR namespace_key = 'user/' || agent.current_user_id()
    );

INSERT INTO agent.schema_migrations (version, description)
VALUES (5, 'Structure LLM Wiki documents and snapshots');

COMMIT;
