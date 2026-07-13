-- Publish Snapshot Batch Claim과 Lease 기반 재처리 상태를 추가한다.

\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE agent.agent_jobs
    ADD COLUMN lease_expires_at timestamptz;

CREATE INDEX ix_agent_jobs_claimable
    ON agent.agent_jobs (status, priority DESC, scheduled_at, created_at)
    WHERE status IN ('queued', 'running');

ALTER TABLE agent.publish_snapshots
    DROP CONSTRAINT publish_snapshots_status_check;

ALTER TABLE agent.publish_snapshots
    ADD CONSTRAINT publish_snapshots_status_check
        CHECK (status IN ('ready', 'claimed', 'published', 'failed', 'superseded')),
    ADD COLUMN claim_id uuid,
    ADD COLUMN claimed_by text,
    ADD COLUMN lease_expires_at timestamptz,
    ADD COLUMN attempt_count integer NOT NULL DEFAULT 0
        CHECK (attempt_count >= 0),
    ADD COLUMN next_attempt_at timestamptz,
    ADD CONSTRAINT publish_snapshot_claim_fields_check CHECK (
        (status = 'claimed'
            AND claim_id IS NOT NULL
            AND claimed_by IS NOT NULL
            AND lease_expires_at IS NOT NULL)
        OR status <> 'claimed'
    );

CREATE INDEX ix_publish_snapshots_claimable
    ON agent.publish_snapshots (
        status,
        next_attempt_at,
        lease_expires_at,
        created_at,
        id
    )
    WHERE status IN ('ready', 'claimed');

ALTER TABLE agent.publish_attempts
    ADD COLUMN claim_id uuid,
    ADD COLUMN claimed_by text,
    ADD COLUMN lease_expires_at timestamptz,
    ADD COLUMN retryable boolean,
    ADD CONSTRAINT uq_publish_attempts_snapshot_claim
        UNIQUE (snapshot_id, claim_id);

CREATE INDEX ix_publish_attempts_claim
    ON agent.publish_attempts (claim_id, snapshot_id)
    WHERE claim_id IS NOT NULL;

INSERT INTO agent.schema_migrations (version, description)
VALUES (2, 'Publish Snapshot batch claim and lease');

COMMIT;
