-- Personal Wiki MCP 검색(MCPTOOL-001)이 인덱스 없는 substring 매칭
-- (position(lower(concat_ws(...))))으로 네임스페이스 전체를 풀스캔하면서,
-- 본문 전체(normalized_content, 최대 200,000자)까지 매 검색마다 lower()로
-- 변환하고 있었다. 오늘 추가한 write 경로(MCPTOOL-003)가 Build 파이프라인을
-- 거치지 않고 원문을 그대로 저장하면서 이 컬럼이 커져 검색이 더 느려졌다.
--
-- pg_trgm(0001에서 이미 설치)의 GIN 인덱스는 ILIKE '%term%' 패턴을 인덱스로
-- 가속할 수 있으므로, 매칭 대상 컬럼에 트라이그램 인덱스를 추가하고
-- 애플리케이션 쿼리를 position(lower(...)) 대신 ILIKE로 전환한다.

BEGIN;

CREATE INDEX IF NOT EXISTS ix_wiki_document_versions_title_trgm
    ON agent.wiki_document_versions USING gin (title gin_trgm_ops);

CREATE INDEX IF NOT EXISTS ix_wiki_document_versions_summary_trgm
    ON agent.wiki_document_versions USING gin (summary gin_trgm_ops);

CREATE INDEX IF NOT EXISTS ix_wiki_document_versions_content_trgm
    ON agent.wiki_document_versions USING gin (normalized_content gin_trgm_ops);

CREATE INDEX IF NOT EXISTS ix_wiki_documents_document_key_trgm
    ON agent.wiki_documents USING gin (document_key gin_trgm_ops);

INSERT INTO agent.schema_migrations (version, description)
VALUES (21, 'Personal Wiki 검색 substring 매칭에 pg_trgm GIN 인덱스 추가')
ON CONFLICT (version) DO NOTHING;

COMMIT;
