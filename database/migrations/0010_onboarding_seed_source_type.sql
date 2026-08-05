-- 온보딩 관심사 시드(WSE-014)를 개인 Wiki 입력원으로 허용한다.
-- 신규 사용자는 저장 근거가 없어 관심사가 비므로, 온보딩 선택을 시드 원본으로
-- 편입해 기존 Wiki Build·관심사 재계산(INT-011) 경로를 그대로 태운다.

BEGIN;

ALTER TABLE agent.wiki_source_events
    DROP CONSTRAINT wiki_source_events_source_type_check;

ALTER TABLE agent.wiki_source_events
    ADD CONSTRAINT wiki_source_events_source_type_check
        CHECK (source_type IN (
            'web_clipping', 'url', 'content_mark', 'content_save', 'memo',
            'edit', 'conversation', 'feedback', 'delete', 'rebuild',
            'onboarding_seed'
        ));

ALTER TABLE agent.user_source_documents
    DROP CONSTRAINT user_source_documents_source_type_check;

ALTER TABLE agent.user_source_documents
    ADD CONSTRAINT user_source_documents_source_type_check
        CHECK (source_type IN (
            'web_clipping', 'url', 'content_mark', 'content_save', 'memo',
            'edit', 'conversation', 'onboarding_seed'
        ));

INSERT INTO agent.schema_migrations (version, description)
VALUES (10, 'Allow onboarding_seed source type for cold-start interest seeding');

COMMIT;
