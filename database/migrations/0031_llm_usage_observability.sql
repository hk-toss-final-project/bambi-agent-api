-- LLM Provider 호출 시도별 사용량·비용·업무 분류를 불변 이력으로 보강한다.

BEGIN;

ALTER TABLE agent.model_configs
    ADD COLUMN cached_input_cost_per_million numeric(14, 6)
        CHECK (
            cached_input_cost_per_million IS NULL
            OR cached_input_cost_per_million >= 0
        );

ALTER TABLE agent.usage_logs
    ADD COLUMN logical_call_id uuid NOT NULL DEFAULT gen_random_uuid(),
    ADD COLUMN attempt_number integer NOT NULL DEFAULT 1
        CHECK (attempt_number > 0),
    ADD COLUMN model_config_id uuid REFERENCES agent.model_configs(id),
    ADD COLUMN workload_type text NOT NULL DEFAULT 'other',
    ADD COLUMN provider_request_id text,
    ADD COLUMN cached_input_tokens integer NOT NULL DEFAULT 0
        CHECK (cached_input_tokens >= 0),
    ADD COLUMN reasoning_output_tokens integer NOT NULL DEFAULT 0
        CHECK (reasoning_output_tokens >= 0),
    ADD COLUMN error_code text,
    ADD COLUMN http_status smallint
        CHECK (http_status IS NULL OR http_status BETWEEN 100 AND 599),
    ADD COLUMN cost_status text NOT NULL DEFAULT 'unknown'
        CHECK (cost_status IN ('calculated', 'unknown', 'not_applicable')),
    ADD COLUMN cost_currency text NOT NULL DEFAULT 'USD',
    ADD COLUMN pricing_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN occurred_at timestamptz;

UPDATE agent.usage_logs
SET occurred_at = created_at
WHERE occurred_at IS NULL;

ALTER TABLE agent.usage_logs
    ALTER COLUMN occurred_at SET NOT NULL,
    ALTER COLUMN occurred_at SET DEFAULT clock_timestamp(),
    ALTER COLUMN estimated_cost DROP NOT NULL,
    ALTER COLUMN estimated_cost DROP DEFAULT,
    ALTER COLUMN estimated_cost TYPE numeric(18, 9),
    DROP CONSTRAINT usage_logs_status_check,
    ADD CONSTRAINT usage_logs_status_check
        CHECK (status IN ('succeeded', 'failed', 'cached', 'cancelled'));

CREATE INDEX ix_usage_logs_workload_occurred
    ON agent.usage_logs (workload_type, occurred_at DESC);
CREATE INDEX ix_usage_logs_operation_occurred
    ON agent.usage_logs (operation, occurred_at DESC);
CREATE INDEX ix_usage_logs_job
    ON agent.usage_logs (job_id, occurred_at)
    WHERE job_id IS NOT NULL;
CREATE INDEX ix_usage_logs_trace
    ON agent.usage_logs (trace_id, occurred_at)
    WHERE trace_id IS NOT NULL;
CREATE INDEX ix_usage_logs_provider_model_occurred
    ON agent.usage_logs (provider, model_name, occurred_at DESC);

-- 2026-08-13 기준 OpenAI 공개 가격을 모델 설정 버전으로 고정한다.
INSERT INTO agent.model_configs (
    config_key,
    version,
    task_type,
    provider,
    model_name,
    parameters,
    input_cost_per_million,
    cached_input_cost_per_million,
    output_cost_per_million,
    status,
    created_by,
    change_reason
)
SELECT
    seed.config_key,
    1,
    seed.task_type,
    'openai',
    seed.model_name,
    seed.parameters,
    seed.input_cost,
    seed.cached_input_cost,
    seed.output_cost,
    'active',
    'migration-0031',
    '2026-08-13 OpenAI 공개 가격표 기준 LLM 사용량 비용 계산'
FROM (
    VALUES
        (
            'usage.openai.gpt-4.1-mini',
            'chat_completion',
            'gpt-4.1-mini',
            '{"batch_discount_ratio": 0.5, "pricing_source": "https://openai.com/index/gpt-4-1/"}'::jsonb,
            0.400000::numeric,
            0.100000::numeric,
            1.600000::numeric
        ),
        (
            'usage.openai.gpt-4o-mini',
            'chat_completion',
            'gpt-4o-mini',
            '{"batch_discount_ratio": 0.5, "pricing_source": "https://openai.com/api/pricing/"}'::jsonb,
            0.150000::numeric,
            0.075000::numeric,
            0.600000::numeric
        ),
        (
            'usage.openai.text-embedding-3-small',
            'embedding',
            'text-embedding-3-small',
            '{"batch_discount_ratio": 0.5, "pricing_source": "https://developers.openai.com/api/docs/models/text-embedding-3-small"}'::jsonb,
            0.020000::numeric,
            NULL::numeric,
            0.000000::numeric
        )
) AS seed(
    config_key,
    task_type,
    model_name,
    parameters,
    input_cost,
    cached_input_cost,
    output_cost
)
WHERE NOT EXISTS (
    SELECT 1
    FROM agent.model_configs AS existing
    WHERE existing.config_key = seed.config_key
);

INSERT INTO agent.schema_migrations (version, description)
VALUES (31, 'Track LLM usage attempts, workload categories, latency, and versioned cost');

COMMIT;
