-- 온보딩에서 선택한 관심 Category·Topic을 사용자 Context Snapshot에 보존한다.
-- Service가 소유한 분류체계의 안정 ID만 복제하고 사용자 원본 Table은 조회하지 않는다.

BEGIN;

ALTER TABLE agent.user_context_snapshots
    ADD COLUMN interest_taxonomy_version text,
    ADD COLUMN selected_category_ids text[] NOT NULL DEFAULT '{}',
    ADD COLUMN selected_topic_ids text[] NOT NULL DEFAULT '{}',
    ADD CONSTRAINT ck_user_context_selected_categories_limit
        CHECK (cardinality(selected_category_ids) <= 8),
    ADD CONSTRAINT ck_user_context_selected_topics_limit
        CHECK (cardinality(selected_topic_ids) <= 12),
    ADD CONSTRAINT ck_user_context_selection_taxonomy_version
        CHECK (
            (cardinality(selected_category_ids) = 0
                AND cardinality(selected_topic_ids) = 0)
            OR interest_taxonomy_version IS NOT NULL
        );

INSERT INTO agent.schema_migrations (version, description)
VALUES (9, 'Store onboarding category and topic selections in user context snapshots');

COMMIT;
