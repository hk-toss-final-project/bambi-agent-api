-- Lease 만료나 Job 종료 뒤에도 running으로 남은 과거 Attempt를 timed_out으로 정리한다.

BEGIN;

UPDATE agent.agent_job_attempts AS attempt
SET status = 'timed_out',
    error_code = 'lease_expired',
    error_message = 'Worker Lease가 만료되거나 Job이 종료되어 실행 시도를 정리했습니다.',
    completed_at = COALESCE(attempt.completed_at, clock_timestamp())
FROM agent.agent_jobs AS job
WHERE job.id = attempt.job_id
  AND attempt.status = 'running'
  AND (
      attempt.attempt_number < job.attempt_count
      OR job.status <> 'running'
      OR job.lease_expires_at IS NULL
      OR job.lease_expires_at < clock_timestamp()
  );

INSERT INTO agent.schema_migrations (version, description)
VALUES (30, 'Mark stale running job attempts as timed out');

COMMIT;
