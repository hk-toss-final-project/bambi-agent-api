-- 아침 브리핑 주제와 사전 수집 근거를 사용자·날짜별 Snapshot으로 보존한다.

BEGIN;

CREATE TABLE agent.briefing_topic_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL,
    briefing_date date NOT NULL,
    topics text[] NOT NULL DEFAULT '{}',
    reason text NOT NULL DEFAULT '',
    candidate_count integer NOT NULL DEFAULT 0 CHECK (candidate_count >= 0),
    contexts_by_topic jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(contexts_by_topic) = 'object'),
    prepared_by_job_id uuid NOT NULL REFERENCES agent.agent_jobs(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (user_id, briefing_date)
);

CREATE INDEX ix_briefing_topic_snapshots_date
    ON agent.briefing_topic_snapshots (briefing_date, user_id);

ALTER TABLE agent.briefing_topic_snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY briefing_topic_snapshot_isolation
    ON agent.briefing_topic_snapshots
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());

CREATE TRIGGER set_briefing_topic_snapshots_updated_at
    BEFORE UPDATE ON agent.briefing_topic_snapshots
    FOR EACH ROW EXECUTE FUNCTION agent.set_updated_at();

INSERT INTO agent.schema_migrations (version, description)
VALUES (28, 'Persist daily briefing topics and prewarmed evidence snapshots');

COMMIT;
