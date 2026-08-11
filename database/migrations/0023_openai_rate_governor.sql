-- OpenAI 동기 호출의 요청·Token 잔여량과 Reset 시각을 PostgreSQL에 공유한다.

\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE agent.provider_rate_limits (
    provider text NOT NULL,
    resource_key text NOT NULL,
    limit_requests bigint NOT NULL CHECK (limit_requests > 0),
    remaining_requests bigint NOT NULL CHECK (remaining_requests >= 0),
    reset_requests_at timestamptz NOT NULL,
    limit_tokens bigint NOT NULL CHECK (limit_tokens > 0),
    remaining_tokens bigint NOT NULL CHECK (remaining_tokens >= 0),
    reset_tokens_at timestamptz NOT NULL,
    blocked_until timestamptz,
    last_request_id text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (provider, resource_key),
    CHECK (remaining_requests <= limit_requests),
    CHECK (remaining_tokens <= limit_tokens)
);

CREATE INDEX ix_provider_rate_limits_blocked
    ON agent.provider_rate_limits (blocked_until)
    WHERE blocked_until IS NOT NULL;

CREATE TRIGGER set_provider_rate_limits_updated_at
    BEFORE UPDATE ON agent.provider_rate_limits
    FOR EACH ROW EXECUTE FUNCTION agent.set_updated_at();

INSERT INTO agent.schema_migrations (version, description)
VALUES (23, 'Persist provider RPM and TPM rate governor state');

COMMIT;
