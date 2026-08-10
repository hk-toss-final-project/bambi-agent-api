-- 수집 실행이 정기(스케줄)인지 수동(운영자 점검)인지 구분한다.
--
-- 일일 실행 한도(daily_max_runs)는 "알아서 도는 수집"을 통제하는 장치다. 그런데
-- 수동 실행(SCH-021)은 한도를 무시하고 돌면서 실행 이력에는 그대로 남는다.
-- runs_today가 그 이력을 전부 세므로, 수동 실행 한 번이 그날의 정기 수집 예산을
-- 먹어버린다.
--
-- 2026-08-10 실측: interest-taxonomy-google-news의 daily_max_runs가 200인데
-- 점검용 수동 실행 두 번으로 runs_today가 414가 됐다. 그 뒤 정기 실행은
-- "남은 횟수 = 200 - 414 = 음수"로 계산해 그날 남은 회차를 전부 건너뛴다.
--
-- 이력은 그대로 남기되(무엇이 언제 돌았는지는 봐야 한다) 한도 집계에서는
-- 정기 실행만 센다.

BEGIN;

ALTER TABLE agent.global_collection_runs
    ADD COLUMN IF NOT EXISTS trigger_source text NOT NULL DEFAULT 'schedule';

ALTER TABLE agent.global_collection_runs
    DROP CONSTRAINT IF EXISTS global_collection_runs_trigger_source_check;

ALTER TABLE agent.global_collection_runs
    ADD CONSTRAINT global_collection_runs_trigger_source_check
    CHECK (trigger_source IN ('schedule', 'manual'));

-- runs_today 집계가 (source_id, started_at, trigger_source)로 훑는다.
CREATE INDEX IF NOT EXISTS ix_global_collection_runs_source_trigger
    ON agent.global_collection_runs (source_id, started_at DESC, trigger_source);

-- 기존 행은 구분 정보가 없다. 대부분 정기 실행이므로 기본값 'schedule'을 그대로
-- 둔다 — 잘못 분류된 과거 수동 실행 몇 건은 자정에 리셋되면서 사라진다.

INSERT INTO agent.schema_migrations (version, description)
VALUES (20, '수집 실행의 정기·수동 구분을 남겨 일일 한도 집계에서 수동을 제외')
ON CONFLICT (version) DO NOTHING;

COMMIT;
