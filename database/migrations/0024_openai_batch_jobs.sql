-- OpenAI Batch 요청, Provider 상태와 custom_id별 결과를 PostgreSQL에 영속화한다.

\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE agent.llm_batches (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider text NOT NULL DEFAULT 'openai',
    endpoint text NOT NULL CHECK (
        endpoint IN ('/v1/responses', '/v1/chat/completions', '/v1/embeddings')
    ),
    model_name text NOT NULL,
    workload text NOT NULL,
    status text NOT NULL DEFAULT 'preparing' CHECK (
        status IN (
            'preparing', 'submitted', 'validating', 'in_progress', 'finalizing',
            'completed', 'failed', 'expired', 'cancelling', 'cancelled'
        )
    ),
    provider_batch_id text UNIQUE,
    input_file_id text,
    output_file_id text,
    error_file_id text,
    completion_window text NOT NULL DEFAULT '24h' CHECK (completion_window = '24h'),
    item_count integer NOT NULL CHECK (item_count > 0),
    next_poll_at timestamptz,
    poll_attempt_count integer NOT NULL DEFAULT 0 CHECK (poll_attempt_count >= 0),
    provider_errors jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    submitted_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE agent.llm_batch_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id uuid REFERENCES agent.llm_batches(id) ON DELETE SET NULL,
    job_id uuid REFERENCES agent.agent_jobs(id) ON DELETE SET NULL,
    user_id text NOT NULL,
    custom_id text NOT NULL UNIQUE,
    provider text NOT NULL DEFAULT 'openai',
    endpoint text NOT NULL CHECK (
        endpoint IN ('/v1/responses', '/v1/chat/completions', '/v1/embeddings')
    ),
    model_name text NOT NULL,
    workload text NOT NULL,
    resource_type text NOT NULL,
    resource_id text NOT NULL,
    request_body jsonb NOT NULL CHECK (jsonb_typeof(request_body) = 'object'),
    context jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'queued' CHECK (
        status IN ('queued', 'preparing', 'submitted', 'completed', 'failed')
    ),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    provider_request_id text,
    response_status_code integer,
    result_body jsonb,
    error jsonb,
    input_tokens bigint CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens bigint CHECK (output_tokens IS NULL OR output_tokens >= 0),
    domain_apply_worker_id text,
    domain_apply_claimed_at timestamptz,
    domain_apply_error text,
    domain_applied_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX ix_llm_batch_items_queue
    ON agent.llm_batch_items (provider, endpoint, model_name, workload, created_at)
    WHERE status = 'queued';
CREATE INDEX ix_llm_batch_items_unapplied
    ON agent.llm_batch_items (workload, updated_at)
    WHERE status = 'completed' AND domain_applied_at IS NULL;
CREATE INDEX ix_llm_batches_due_poll
    ON agent.llm_batches (next_poll_at, created_at)
    WHERE status IN ('submitted', 'validating', 'in_progress', 'finalizing', 'cancelling');

CREATE TRIGGER set_llm_batches_updated_at
    BEFORE UPDATE ON agent.llm_batches
    FOR EACH ROW EXECUTE FUNCTION agent.set_updated_at();
CREATE TRIGGER set_llm_batch_items_updated_at
    BEFORE UPDATE ON agent.llm_batch_items
    FOR EACH ROW EXECUTE FUNCTION agent.set_updated_at();

ALTER TABLE agent.llm_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.llm_batch_items ENABLE ROW LEVEL SECURITY;

CREATE POLICY llm_batch_system_access ON agent.llm_batches
    USING (agent.has_system_scope())
    WITH CHECK (agent.has_system_scope());
CREATE POLICY llm_batch_item_isolation ON agent.llm_batch_items
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());

INSERT INTO agent.schema_migrations (version, description)
VALUES (24, 'Persist OpenAI Batch requests and custom id results');

COMMIT;
