-- OpenAI Batch 대기 중 Worker Lease를 해제하는 Agent Job 상태를 추가한다.

\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE agent.agent_jobs
    DROP CONSTRAINT agent_jobs_status_check;
ALTER TABLE agent.agent_jobs
    ADD CONSTRAINT agent_jobs_status_check CHECK (
        status IN (
            'queued', 'running', 'waiting_provider', 'completed', 'failed',
            'cancelled', 'dead_letter'
        )
    );

CREATE INDEX ix_agent_jobs_waiting_provider
    ON agent.agent_jobs (updated_at, id)
    WHERE status = 'waiting_provider';

INSERT INTO agent.schema_migrations (version, description)
VALUES (25, 'Add waiting provider status for asynchronous LLM batches');

COMMIT;
