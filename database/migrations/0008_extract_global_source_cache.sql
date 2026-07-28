-- Global 수집 원문을 LLM Wiki 테이블에서 분리해 소유권 없는 수집 캐시로 옮긴다.
--
-- 배경: wiki_documents는 "맥락 주체(namespace)"별 LLM Wiki 문서를 담는 테이블인데,
-- Global 뉴스 수집 원문이 namespace_key='global'로 같은 테이블에 저장되면서
-- 성격이 다른 두 데이터(개인 맥락 위키 노드 vs 소유자 없는 수집 캐시)가 섞였다.
-- Global 수집물은 위키 노드가 아니라 "LLM이 URL을 직접 읽을 수 없으니 한 번
-- 읽은 본문을 모두가 재사용하는 캐시"이므로, user_source_documents와 대칭인
-- 별도 테이블로 분리한다. 수집 파이프라인 상태(content_status)도 JSONB
-- metadata가 아닌 정식 컬럼으로 승격한다.
--
-- 이후 wiki_documents의 global namespace 행은 만들지 않는다. 기존 행은
-- (로컬·초기 배포 기준 0건 확인) 참조 테이블부터 정리하고 제거한다.
-- Version·Chunk·Embedding은 FK CASCADE로 함께 정리된다.

BEGIN;

CREATE TABLE agent.global_source_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_url text NOT NULL UNIQUE,
    -- URL의 SHA-256 앞 24자. 수집 워커가 만드는 안정적 캐시 Key.
    url_key text NOT NULL UNIQUE,
    provider text NOT NULL,
    search_query text,
    source_name text,
    language text NOT NULL DEFAULT 'und',
    title text NOT NULL DEFAULT '',
    description text,
    -- Jina Reader가 채우는 본문 Markdown. pending 동안 NULL이다.
    markdown text,
    content_hash text CHECK (content_hash IS NULL OR length(content_hash) = 64),
    content_status text NOT NULL DEFAULT 'pending'
        CHECK (content_status IN ('pending', 'fetching', 'fetched', 'failed')),
    -- Jina Reader가 리다이렉트까지 반영한 최종 URL.
    resolved_url text,
    fetch_error_code text,
    fetch_error_message text,
    published_at timestamptz,
    fetched_at timestamptz,
    -- Report Builder Keyword 검색용. 본문이 비정상적으로 길어도 tsvector 한계를
    -- 넘지 않도록 앞부분만 색인한다.
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector(
            'simple',
            left(
                coalesce(title, '') || ' ' || coalesce(description, '') || ' '
                    || coalesce(markdown, ''),
                200000
            )
        )
    ) STORED,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- 본문 수집 워커의 pending Batch 점유 순서.
CREATE INDEX ix_global_source_documents_claim
    ON agent.global_source_documents (updated_at)
    WHERE content_status = 'pending';
-- 검색 폴백(최근 fetched 문서)과 본문 재사용 조회.
CREATE INDEX ix_global_source_documents_fetched_recent
    ON agent.global_source_documents (updated_at DESC)
    WHERE content_status = 'fetched';
CREATE INDEX ix_global_source_documents_search_vector
    ON agent.global_source_documents USING gin (search_vector)
    WHERE content_status = 'fetched';
CREATE INDEX ix_global_source_documents_markdown_trgm
    ON agent.global_source_documents USING gin (markdown gin_trgm_ops)
    WHERE content_status = 'fetched';

ALTER TABLE agent.global_source_documents ENABLE ROW LEVEL SECURITY;

-- 수집 캐시는 소유자가 없다: 읽기는 모든 Scope에 허용하고, 쓰기는 수집
-- Worker의 system Scope만 허용한다.
CREATE POLICY global_source_document_read ON agent.global_source_documents
    FOR SELECT
    USING (true);
CREATE POLICY global_source_document_write ON agent.global_source_documents
    FOR ALL
    USING (agent.has_system_scope())
    WITH CHECK (agent.has_system_scope());

CREATE TRIGGER set_global_source_documents_updated_at
    BEFORE UPDATE ON agent.global_source_documents
    FOR EACH ROW EXECUTE FUNCTION agent.set_updated_at();

-- Citation이 Global 캐시 문서를 출처로 가리킬 수 있게 한다. 기존
-- document_version_id·chunk_id는 개인 Wiki 출처 전용이 된다.
ALTER TABLE agent.citations
    ADD COLUMN global_source_document_id uuid
        REFERENCES agent.global_source_documents(id);

-- 기존 global namespace Wiki 행 제거. CASCADE가 없는 참조 테이블을 먼저 정리한다.
-- 과거 global 문서를 가리키던 Citation은 URL이 출처 증빙으로 남는다.
UPDATE agent.citations
SET document_version_id = NULL,
    chunk_id = NULL
WHERE document_version_id IN (
    SELECT id FROM agent.wiki_document_versions WHERE namespace_key = 'global'
)
   OR chunk_id IN (
    SELECT id FROM agent.wiki_chunks WHERE namespace_key = 'global'
);
DELETE FROM agent.interest_evidence
WHERE document_id IN (
    SELECT id FROM agent.wiki_documents WHERE namespace_key = 'global'
);
DELETE FROM agent.global_trend_documents
WHERE document_id IN (
    SELECT id FROM agent.wiki_documents WHERE namespace_key = 'global'
);
DELETE FROM agent.discovery_candidates
WHERE document_id IN (
    SELECT id FROM agent.wiki_documents WHERE namespace_key = 'global'
);
DELETE FROM agent.wiki_documents WHERE namespace_key = 'global';

INSERT INTO agent.schema_migrations (version, description)
VALUES (8, 'Extract global collected articles into an ownerless source cache table');

COMMIT;
