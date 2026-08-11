-- Global 수집 캐시가 원문 본문과 함께 대표 이미지 URL을 보존한다.
-- Report Builder는 리포트가 실제로 인용한 캐시 문서 중 하나를 상단 이미지로
-- 선택하며, 이미지 수집 실패는 본문 수집·리포트 생성을 막지 않는다.

BEGIN;

ALTER TABLE agent.global_source_documents
    ADD COLUMN image_url text;

COMMENT ON COLUMN agent.global_source_documents.image_url IS
    'Jina Image 헤더 또는 Provider 메타데이터에서 얻은 원문 대표 이미지 URL';

INSERT INTO agent.schema_migrations (version, description)
VALUES (26, 'Store representative image URLs for global source documents');

COMMIT;
