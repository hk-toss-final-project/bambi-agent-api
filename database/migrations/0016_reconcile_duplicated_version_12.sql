-- 중복된 version 12 중 누락될 수 있었던 Global 검색 본문 Schema를 복구한다.
--
-- 0012_change_history_delta.sql과 0012_global_source_search_body.sql이 함께 있던
-- 새 DB에서는 파일명 순서상 change_history가 version 12를 먼저 기록했다. 그러면
-- 검색 본문 Migration은 건너뛰어져 search_body와 관련 색인이 만들어지지 않는다.
-- 운영 DB처럼 search_body 쪽이 이미 적용된 경우에는 DDL을 반복하지 않고 version
-- 16만 기록한다.

\set ON_ERROR_STOP on

BEGIN;

SELECT NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'agent'
      AND table_name = 'global_source_documents'
      AND column_name = 'search_body'
) AS should_repair_search_body \gset

\if :should_repair_search_body
ALTER TABLE agent.global_source_documents
    ADD COLUMN IF NOT EXISTS search_body text;

COMMENT ON COLUMN agent.global_source_documents.search_body IS
    '검색 색인용 정제 본문. 페이지 메뉴·관련기사를 걷어낸 기사 본문(상한 6,000자). NULL이면 markdown으로 대체한다.';

DROP INDEX IF EXISTS agent.ix_global_source_documents_search_vector;
ALTER TABLE agent.global_source_documents DROP COLUMN IF EXISTS search_vector;

ALTER TABLE agent.global_source_documents
    ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector(
            'simple',
            left(
                coalesce(title, '') || ' ' || coalesce(description, '') || ' '
                    || coalesce(search_body, markdown, ''),
                200000
            )
        )
    ) STORED;

CREATE INDEX IF NOT EXISTS ix_global_source_documents_search_vector
    ON agent.global_source_documents USING gin (search_vector)
    WHERE content_status = 'fetched';

DROP INDEX IF EXISTS agent.ix_global_source_documents_markdown_trgm;
CREATE INDEX IF NOT EXISTS ix_global_source_documents_search_body_trgm
    ON agent.global_source_documents
    USING gin ((coalesce(search_body, markdown)) gin_trgm_ops)
    WHERE content_status = 'fetched';
\endif

INSERT INTO agent.schema_migrations (version, description)
VALUES (16, 'Reconcile the skipped Global search body migration from duplicated version 12');

COMMIT;
