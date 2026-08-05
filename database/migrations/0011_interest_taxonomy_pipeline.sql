-- Service DB가 소유한 관심사 taxonomy를 Agent DB에 버전 Snapshot으로 복제하고,
-- Topic별 수집 대상과 사용자 구독을 관리한다.

BEGIN;

CREATE TABLE agent.interest_taxonomy_versions (
    version text PRIMARY KEY,
    source_hash text NOT NULL CHECK (length(source_hash) = 64),
    locale text NOT NULL DEFAULT 'ko-KR',
    received_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE agent.interest_taxonomy_categories (
    taxonomy_version text NOT NULL
        REFERENCES agent.interest_taxonomy_versions(version) ON DELETE CASCADE,
    category_id text NOT NULL,
    name text NOT NULL,
    name_en text NOT NULL,
    description text NOT NULL,
    emoji text NOT NULL,
    display_order integer NOT NULL CHECK (display_order >= 0),
    PRIMARY KEY (taxonomy_version, category_id)
);

CREATE TABLE agent.interest_taxonomy_topics (
    taxonomy_version text NOT NULL,
    topic_id text NOT NULL,
    category_id text NOT NULL,
    name text NOT NULL,
    name_en text NOT NULL,
    description text NOT NULL,
    display_order integer NOT NULL CHECK (display_order >= 0),
    keywords jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(keywords) = 'array'),
    PRIMARY KEY (taxonomy_version, topic_id),
    FOREIGN KEY (taxonomy_version, category_id)
        REFERENCES agent.interest_taxonomy_categories(taxonomy_version, category_id)
        ON DELETE CASCADE
);

CREATE TABLE agent.interest_collection_targets (
    target_key text PRIMARY KEY,
    target_type text NOT NULL CHECK (target_type IN ('taxonomy', 'custom')),
    taxonomy_version text,
    topic_id text,
    category_id text,
    query text NOT NULL,
    category_name text,
    preferred_provider text NOT NULL DEFAULT 'google_news',
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'paused', 'retired')),
    subscriber_count integer NOT NULL DEFAULT 0 CHECK (subscriber_count >= 0),
    refresh_interval_minutes integer NOT NULL DEFAULT 360
        CHECK (refresh_interval_minutes BETWEEN 30 AND 10080),
    next_collection_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_collected_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (taxonomy_version, topic_id)
        REFERENCES agent.interest_taxonomy_topics(taxonomy_version, topic_id),
    CHECK (
        (target_type = 'taxonomy' AND taxonomy_version IS NOT NULL
            AND topic_id IS NOT NULL AND category_id IS NOT NULL)
        OR
        (target_type = 'custom' AND taxonomy_version IS NULL
            AND topic_id IS NULL AND category_id IS NULL AND category_name IS NULL)
    )
);

CREATE INDEX ix_interest_collection_targets_due
    ON agent.interest_collection_targets (
        preferred_provider, next_collection_at, subscriber_count DESC
    )
    WHERE status = 'active';

CREATE TABLE agent.user_interest_subscriptions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL,
    target_key text NOT NULL REFERENCES agent.interest_collection_targets(target_key),
    context_snapshot_id uuid NOT NULL
        REFERENCES agent.user_context_snapshots(id) ON DELETE CASCADE,
    topic_name text NOT NULL,
    category_name text,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE UNIQUE INDEX uq_user_interest_subscriptions_active
    ON agent.user_interest_subscriptions (user_id, target_key)
    WHERE active;
CREATE INDEX ix_user_interest_subscriptions_user
    ON agent.user_interest_subscriptions (user_id, active, updated_at DESC);

CREATE TABLE agent.global_source_document_topics (
    global_source_document_id uuid NOT NULL
        REFERENCES agent.global_source_documents(id) ON DELETE CASCADE,
    target_key text NOT NULL
        REFERENCES agent.interest_collection_targets(target_key) ON DELETE CASCADE,
    search_query text NOT NULL,
    discovered_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (global_source_document_id, target_key)
);

CREATE INDEX ix_global_source_document_topics_target
    ON agent.global_source_document_topics (target_key, discovered_at DESC);

-- Taxonomy/수집 대상은 소유권 없는 Global 설정이며 사용자 구독만 사용자별로 격리한다.
ALTER TABLE agent.interest_taxonomy_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.interest_taxonomy_categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.interest_taxonomy_topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.interest_collection_targets ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.user_interest_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.global_source_document_topics ENABLE ROW LEVEL SECURITY;

CREATE POLICY interest_taxonomy_version_read ON agent.interest_taxonomy_versions
    FOR SELECT USING (true);
CREATE POLICY interest_taxonomy_version_write ON agent.interest_taxonomy_versions
    FOR ALL USING (agent.has_system_scope()) WITH CHECK (agent.has_system_scope());
CREATE POLICY interest_taxonomy_category_read ON agent.interest_taxonomy_categories
    FOR SELECT USING (true);
CREATE POLICY interest_taxonomy_category_write ON agent.interest_taxonomy_categories
    FOR ALL USING (agent.has_system_scope()) WITH CHECK (agent.has_system_scope());
CREATE POLICY interest_taxonomy_topic_read ON agent.interest_taxonomy_topics
    FOR SELECT USING (true);
CREATE POLICY interest_taxonomy_topic_write ON agent.interest_taxonomy_topics
    FOR ALL USING (agent.has_system_scope()) WITH CHECK (agent.has_system_scope());
CREATE POLICY interest_collection_target_read ON agent.interest_collection_targets
    FOR SELECT USING (true);
CREATE POLICY interest_collection_target_write ON agent.interest_collection_targets
    FOR ALL USING (agent.has_system_scope()) WITH CHECK (agent.has_system_scope());
CREATE POLICY user_interest_subscription_isolation ON agent.user_interest_subscriptions
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());
CREATE POLICY global_source_document_topic_read ON agent.global_source_document_topics
    FOR SELECT USING (true);
CREATE POLICY global_source_document_topic_write ON agent.global_source_document_topics
    FOR ALL USING (agent.has_system_scope()) WITH CHECK (agent.has_system_scope());

CREATE TRIGGER set_interest_collection_targets_updated_at
    BEFORE UPDATE ON agent.interest_collection_targets
    FOR EACH ROW EXECUTE FUNCTION agent.set_updated_at();
CREATE TRIGGER set_user_interest_subscriptions_updated_at
    BEFORE UPDATE ON agent.user_interest_subscriptions
    FOR EACH ROW EXECUTE FUNCTION agent.set_updated_at();

-- 모든 taxonomy/custom 대상 질의를 6시간마다 Google News RSS로 순차 수집한다.
INSERT INTO agent.global_sources (
    source_key, connector_type, display_name, status, schedule_cron,
    keywords, languages, quota_policy, connector_config
) VALUES (
    'interest-taxonomy-google-news',
    'google_news',
    'Interest taxonomy Google News',
    'active',
    '0 */6 * * *',
    '{}',
    ARRAY['ko'],
    '{"daily_max_runs": 200}'::jsonb,
    '{"managed_by": "interest-taxonomy", "limit_per_provider": 10}'::jsonb
)
ON CONFLICT (source_key) DO NOTHING;

INSERT INTO agent.schema_migrations (version, description)
VALUES (11, 'Store interest taxonomy snapshots and scheduled topic collection targets');

COMMIT;
