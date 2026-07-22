-- 기존 리포트 생성 Job과 기능 ID를 Report Builder 명칭으로 이전한다.

BEGIN;

UPDATE agent.agent_jobs
SET
    job_type = 'report_generation',
    updated_at = clock_timestamp()
WHERE job_type = 'bambi_generation';

UPDATE agent.agent_jobs
SET
    feature_id = 'REPORT-' || substring(feature_id FROM 7),
    updated_at = clock_timestamp()
WHERE feature_id LIKE 'BAMBI-%';

UPDATE agent.usage_logs
SET feature_id = 'REPORT-' || substring(feature_id FROM 7)
WHERE feature_id LIKE 'BAMBI-%';

INSERT INTO agent.schema_migrations (version, description)
VALUES (6, 'Rename legacy generation contracts to Report Builder');

COMMIT;
