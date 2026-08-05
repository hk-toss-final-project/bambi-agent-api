-- Global 수집 문서의 **검색 색인 대상**을 페이지 통짜에서 기사 본문으로 좁힌다.
--
-- Jina Reader는 페이지 전체를 Markdown으로 옮긴다. 그래서 저장된 본문에는 사이트
-- 메뉴·관련기사 목록·광고가 함께 들어 있고, 평균 26,730자에 달한다(2026-08-05
-- 실측, 최근 60건). 이 상태로 색인하면 관련기사 목록에 낀 단어 하나로 무관한
-- 문서가 검색에 걸린다.
--
--   실측: '블록체인' 검색에 방탄소년단 기사가 걸렸고, 본문 3.8만 자 어딘가에
--         실제로 그 단어가 있었다. '프로야구' 검색에는 반도체 기사만 6건 나왔다.
--
-- markdown은 그대로 둔다 — 리포트 인용(quoted_text)과 본문 표시에 필요하고,
-- 되돌릴 때 검색 대상만 원위치하면 되기 때문이다. 검색용 정제본을 옆에 둔다.
--
-- 정제 상한 6,000자는 실측으로 정했다(2026-08-05, 최근 60건).
--
--   상한 2,000자   잡음 블록체인 5→1건이지만 신호도 전기차 9→1건으로 죽는다
--   상한 6,000자   잡음 블록체인 5→3건, 신호는 반도체 93%·코스피 94% 유지
--
-- search_body가 비어 있는 동안에는 markdown으로 대체한다(COALESCE). 백필이
-- 끝나기 전에도 검색이 그대로 동작하게 하려는 것이다.

BEGIN;

ALTER TABLE agent.global_source_documents
    -- 검색 색인용 기사 본문. 애플리케이션이 채운다(본문 시작점 탐지에 정규식이
    -- 필요해 생성 컬럼으로 만들 수 없다).
    ADD COLUMN IF NOT EXISTS search_body text;

COMMENT ON COLUMN agent.global_source_documents.search_body IS
    '검색 색인용 정제 본문. 페이지 메뉴·관련기사를 걷어낸 기사 본문(상한 6,000자). NULL이면 markdown으로 대체한다.';

-- 생성 컬럼은 식을 바꿀 수 없어 다시 만든다. 인덱스도 함께 재생성된다.
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

-- Trigram 검색도 같은 대상을 본다. 질의가 쓰는 식과 정확히 같아야 인덱스를 탄다.
DROP INDEX IF EXISTS agent.ix_global_source_documents_markdown_trgm;
CREATE INDEX IF NOT EXISTS ix_global_source_documents_search_body_trgm
    ON agent.global_source_documents
    USING gin ((coalesce(search_body, markdown)) gin_trgm_ops)
    WHERE content_status = 'fetched';

INSERT INTO agent.schema_migrations (version, description)
VALUES (12, 'Index cleaned article body instead of the whole captured page');

COMMIT;
