-- Wiki 관계의 현재 상태와 원본별 근거 이력을 분리해 보존한다.

\set ON_ERROR_STOP on

BEGIN;

-- 기존 복합 PK는 기존 INSERT ... ON CONFLICT 계약을 위해 유지하고, 근거 테이블이
-- 안정적으로 참조할 수 있는 대체 식별자를 추가한다.
ALTER TABLE agent.wiki_document_relations
    DROP CONSTRAINT wiki_document_relations_relation_type_check,
    ADD COLUMN id uuid NOT NULL DEFAULT gen_random_uuid(),
    ADD COLUMN status text NOT NULL DEFAULT 'active',
    ADD COLUMN provenance_kind text NOT NULL DEFAULT 'source_explicit',
    ADD COLUMN confidence numeric(8,6) NOT NULL DEFAULT 1.0,
    ADD COLUMN review_status text NOT NULL DEFAULT 'unreviewed',
    ADD COLUMN model_name text,
    ADD COLUMN model_version text,
    ADD COLUMN prompt_key text,
    ADD COLUMN prompt_version text,
    ADD COLUMN updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    ADD COLUMN superseded_at timestamptz,
    ADD CONSTRAINT wiki_document_relations_id_namespace_key_key
        UNIQUE (id, namespace_key),
    ADD CONSTRAINT wiki_document_relations_relation_type_check
        CHECK (relation_type IN (
            'entity_relation',
            'applies_concept',
            'related_concept',
            'alias_of',
            'instance_of',
            'subtopic_of',
            'part_of',
            'located_in',
            'occurs_in',
            'affects',
            'causes',
            'associated_with'
        )),
    ADD CONSTRAINT wiki_document_relations_status_check
        CHECK (status IN ('active', 'superseded')),
    ADD CONSTRAINT wiki_document_relations_provenance_kind_check
        CHECK (provenance_kind IN (
            'source_explicit',
            'semantic_inference',
            'user_declared',
            'system_rule'
        )),
    ADD CONSTRAINT wiki_document_relations_confidence_check
        CHECK (confidence >= 0 AND confidence <= 1),
    ADD CONSTRAINT wiki_document_relations_review_status_check
        CHECK (review_status IN ('unreviewed', 'accepted', 'rejected')),
    ADD CONSTRAINT wiki_document_relations_lifecycle_check
        CHECK (
            (status = 'active' AND superseded_at IS NULL)
            OR (status = 'superseded' AND superseded_at IS NOT NULL)
        );

CREATE INDEX ix_wiki_document_relations_active_source
    ON agent.wiki_document_relations (
        namespace_key,
        source_document_id,
        relation_type
    )
    WHERE status = 'active' AND review_status <> 'rejected';

CREATE INDEX ix_wiki_document_relations_active_target
    ON agent.wiki_document_relations (
        namespace_key,
        target_document_id,
        relation_type
    )
    WHERE status = 'active' AND review_status <> 'rejected';

CREATE TRIGGER set_wiki_document_relations_updated_at
    BEFORE UPDATE ON agent.wiki_document_relations
    FOR EACH ROW EXECUTE FUNCTION agent.set_updated_at();

-- 같은 관계를 여러 원본·여러 Build가 지지할 수 있으므로 출처별 판정 이력을
-- 별도 Row로 보존한다. 새 Build는 이전 active Row를 supersede한 뒤 새 판정을
-- 추가하며, 같은 Job 재시도는 아래 Unique 제약으로 멱등 갱신한다.
CREATE TABLE agent.wiki_relation_supports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    relation_id uuid NOT NULL,
    namespace_key text NOT NULL,
    source_document_version_id uuid NOT NULL,
    build_job_id uuid NOT NULL REFERENCES agent.agent_jobs(id),
    provenance_kind text NOT NULL
        CHECK (provenance_kind IN (
            'source_explicit',
            'semantic_inference',
            'user_declared',
            'system_rule'
        )),
    confidence numeric(8,6) NOT NULL
        CHECK (confidence >= 0 AND confidence <= 1),
    review_status text NOT NULL DEFAULT 'unreviewed'
        CHECK (review_status IN ('unreviewed', 'accepted', 'rejected')),
    evidence text,
    model_name text,
    model_version text,
    prompt_key text,
    prompt_version text,
    metadata jsonb NOT NULL DEFAULT '{}',
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'superseded')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    superseded_at timestamptz,
    UNIQUE (relation_id, source_document_version_id, build_job_id),
    FOREIGN KEY (relation_id, namespace_key)
        REFERENCES agent.wiki_document_relations(id, namespace_key)
        ON DELETE CASCADE,
    FOREIGN KEY (source_document_version_id, namespace_key)
        REFERENCES agent.user_source_document_versions(id, namespace_key)
        ON DELETE CASCADE,
    CHECK (
        (status = 'active' AND superseded_at IS NULL)
        OR (status = 'superseded' AND superseded_at IS NOT NULL)
    )
);

CREATE INDEX ix_wiki_relation_supports_source_active
    ON agent.wiki_relation_supports (
        namespace_key,
        source_document_version_id,
        relation_id
    )
    WHERE status = 'active';

CREATE INDEX ix_wiki_relation_supports_relation_active
    ON agent.wiki_relation_supports (namespace_key, relation_id, confidence DESC)
    WHERE status = 'active';

CREATE TRIGGER set_wiki_relation_supports_updated_at
    BEFORE UPDATE ON agent.wiki_relation_supports
    FOR EACH ROW EXECUTE FUNCTION agent.set_updated_at();

-- 원본 삭제의 ON DELETE CASCADE가 support를 지울 때도 근거 없는 active Head가
-- 남지 않게 한다. Build 동기화 경로는 같은 판정을 집계 Metadata와 함께 한 번 더
-- 수행하지만, 이 Trigger가 직접 삭제·개인정보 정리 경로의 안전망이 된다.
CREATE FUNCTION agent.supersede_wiki_relation_without_support()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE agent.wiki_document_relations AS relation
    SET
        status = 'superseded',
        superseded_at = COALESCE(relation.superseded_at, clock_timestamp())
    WHERE relation.id = OLD.relation_id
      AND relation.namespace_key = OLD.namespace_key
      AND relation.status = 'active'
      AND NOT EXISTS (
            SELECT 1
            FROM agent.wiki_relation_supports AS support
            WHERE support.relation_id = relation.id
              AND support.namespace_key = relation.namespace_key
              AND support.status = 'active'
      );
    RETURN OLD;
END;
$$;

CREATE TRIGGER supersede_wiki_relation_after_support_delete
    AFTER DELETE ON agent.wiki_relation_supports
    FOR EACH ROW EXECUTE FUNCTION agent.supersede_wiki_relation_without_support();

ALTER TABLE agent.wiki_relation_supports ENABLE ROW LEVEL SECURITY;

CREATE POLICY wiki_relation_support_read ON agent.wiki_relation_supports
    FOR SELECT
    USING (
        agent.has_system_scope()
        OR namespace_key = 'user/' || agent.current_user_id()
    );

CREATE POLICY wiki_relation_support_write ON agent.wiki_relation_supports
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
VALUES (17, 'Track Wiki relation provenance supports and lifecycle');

COMMIT;
