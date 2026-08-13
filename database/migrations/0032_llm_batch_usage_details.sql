-- OpenAI Batch Item의 캐시·Reasoning Token을 보존하고 Embedding Batch 단가를 교정한다.

BEGIN;

ALTER TABLE agent.llm_batch_items
    ADD COLUMN cached_input_tokens bigint
        CHECK (cached_input_tokens IS NULL OR cached_input_tokens >= 0),
    ADD COLUMN reasoning_output_tokens bigint
        CHECK (reasoning_output_tokens IS NULL OR reasoning_output_tokens >= 0);

WITH retired AS (
    UPDATE agent.model_configs
    SET status = 'retired'
    WHERE config_key = 'usage.openai.text-embedding-3-small'
      AND plan IS NULL
      AND status = 'active'
    RETURNING *
), versioned AS (
    SELECT
        retired.*,
        (
            SELECT COALESCE(max(existing.version), 0) + 1
            FROM agent.model_configs AS existing
            WHERE existing.config_key = retired.config_key
        ) AS next_version
    FROM retired
)
INSERT INTO agent.model_configs (
    config_key,
    version,
    task_type,
    plan,
    provider,
    model_name,
    parameters,
    fallback_order,
    input_cost_per_million,
    cached_input_cost_per_million,
    output_cost_per_million,
    status,
    created_by,
    change_reason
)
SELECT
    config_key,
    next_version,
    task_type,
    plan,
    provider,
    model_name,
    jsonb_set(parameters, '{batch_discount_ratio}', '1'::jsonb, true),
    fallback_order,
    input_cost_per_million,
    cached_input_cost_per_million,
    output_cost_per_million,
    'active',
    'migration-0032',
    'OpenAI text-embedding-3-small Batch 공개 단가 $0.02/1M 반영'
FROM versioned;

INSERT INTO agent.schema_migrations (version, description)
VALUES (32, 'Track OpenAI Batch token details and correct embedding batch price');

COMMIT;
