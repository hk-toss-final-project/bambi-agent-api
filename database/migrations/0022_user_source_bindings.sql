-- 사용자 원본 Head를 재사용한 여러 저장 이벤트의 활성 참조를 추적한다.

\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE agent.user_source_bindings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL,
    namespace_key text NOT NULL,
    source_document_id uuid NOT NULL,
    source_document_version_id uuid NOT NULL,
    source_event_row_id uuid NOT NULL,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'deleted')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    deleted_at timestamptz,
    UNIQUE (source_event_row_id),
    FOREIGN KEY (source_document_id, namespace_key)
        REFERENCES agent.user_source_documents(id, namespace_key) ON DELETE CASCADE,
    FOREIGN KEY (source_document_version_id, namespace_key)
        REFERENCES agent.user_source_document_versions(id, namespace_key) ON DELETE CASCADE,
    FOREIGN KEY (source_event_row_id)
        REFERENCES agent.wiki_source_events(id) ON DELETE CASCADE,
    CHECK (namespace_key = 'user/' || user_id),
    CHECK (
        (status = 'active' AND deleted_at IS NULL)
        OR (status = 'deleted' AND deleted_at IS NOT NULL)
    )
);

CREATE INDEX ix_user_source_bindings_active_document
    ON agent.user_source_bindings (namespace_key, source_document_id)
    WHERE status = 'active';

-- 기존 Version이 직접 참조하던 Source Event는 활성 바인딩으로 이관한다.
INSERT INTO agent.user_source_bindings (
    user_id,
    namespace_key,
    source_document_id,
    source_document_version_id,
    source_event_row_id
)
SELECT
    document.user_id,
    document.namespace_key,
    document.id,
    version.id,
    version.source_event_id
FROM agent.user_source_document_versions AS version
JOIN agent.user_source_documents AS document
  ON document.id = version.source_document_id
 AND document.namespace_key = version.namespace_key
WHERE version.source_event_id IS NOT NULL
ON CONFLICT (source_event_row_id) DO NOTHING;

ALTER TABLE agent.user_source_bindings ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_source_binding_read ON agent.user_source_bindings
    FOR SELECT
    USING (
        agent.has_system_scope()
        OR namespace_key = 'user/' || agent.current_user_id()
    );

CREATE POLICY user_source_binding_write ON agent.user_source_bindings
    FOR ALL
    USING (
        agent.has_system_scope()
        OR namespace_key = 'user/' || agent.current_user_id()
    )
    WITH CHECK (
        agent.has_system_scope()
        OR namespace_key = 'user/' || agent.current_user_id()
    );

INSERT INTO agent.schema_migrations (version, description)
VALUES (22, 'Track active source event bindings for safe removal');

COMMIT;
