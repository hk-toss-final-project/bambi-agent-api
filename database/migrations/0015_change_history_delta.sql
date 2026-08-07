-- 0012_change_history_delta.sql 재발행(2026-08-07).
--
-- 왜 재발행하는가: 0012 번호가 0012_global_source_search_body.sql 과 겹쳤다.
-- 러너는 파일명 접두사로 version 을 뽑고 schema_migrations 에 그 version 이 이미
-- 있으면 건너뛴다. 운영 DB는 0012_global_source_search_body 가 먼저(08-05) 적용돼
-- version 12 를 기록했고, 뒤에 들어온 delta(08-06)는 "이미 적용됨"으로 조용히
-- 건너뛰어졌다. 배포 로그에 `Skipping applied migration 0012_change_history_delta.sql`
-- 로 남지만 실패가 아니라 눈에 띄지 않았다. 결과적으로 Delta 추적 에이전트 코드는
-- 배포됐는데 테이블이 없는 상태였다(change_history_enabled 기본 false 라 아직 표면화 X).
--
-- 원본 0012_change_history_delta.sql 은 삭제한다. 남겨두면 새 DB에서 알파벳 순서상
-- delta 가 먼저 적용돼 version 12 를 선점하고, 이번엔 global_source_search_body 가
-- 건너뛰어지는 정반대 사고가 난다.
--
-- 모든 DDL 에 존재 검사를 붙였다. delta 가 version 12 로 이미 적용된 로컬 DB 에서도
-- 안전하게 재실행된다. 내용은 원본과 동일하며 스키마 변경은 없다.

\set ON_ERROR_STOP on

BEGIN;

-- 한 번의 변경점 추적 실행. "직전 보고서 시점"을 날짜가 아니라 이 실행 기록으로
-- 잡는다(매일 돌지 않아도 델타가 끊기지 않게 한다).
CREATE TABLE IF NOT EXISTS agent.change_history_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL,
    topic text NOT NULL,
    job_id uuid REFERENCES agent.agent_jobs(id),
    generation_run_id uuid REFERENCES agent.generation_runs(id),
    -- 이 실행이 대조 대상으로 삼은 직전 실행. 첫 실행이면 NULL이다.
    base_run_id uuid REFERENCES agent.change_history_runs(id),
    reference_date date NOT NULL,
    is_first_run boolean NOT NULL DEFAULT false,
    outcome text NOT NULL DEFAULT 'delta'
        CHECK (outcome IN ('delta', 'no_change', 'failed')),
    new_fact_count integer NOT NULL DEFAULT 0 CHECK (new_fact_count >= 0),
    updated_fact_count integer NOT NULL DEFAULT 0 CHECK (updated_fact_count >= 0),
    duplicate_fact_count integer NOT NULL DEFAULT 0 CHECK (duplicate_fact_count >= 0),
    -- 검증(5번)에서 드롭된 항목과 사유. 무한 루프 대신 남기는 흔적이다.
    dropped_flags jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(dropped_flags) = 'array'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS ix_change_history_runs_latest
    ON agent.change_history_runs (user_id, topic, created_at DESC);

-- 팩트 하나 = (subject, attribute, fact_value) 세 요소. 중복·갱신 판정은
-- (subject, attribute) 매칭으로 하고, fact_value가 다르면 갱신으로 본다.
CREATE TABLE IF NOT EXISTS agent.change_history_facts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES agent.change_history_runs(id) ON DELETE CASCADE,
    user_id text NOT NULL,
    topic text NOT NULL,
    subject text NOT NULL CHECK (length(subject) > 0),
    attribute text NOT NULL CHECK (length(attribute) > 0),
    fact_value text NOT NULL DEFAULT '',
    statement text NOT NULL CHECK (length(statement) > 0),
    verdict text NOT NULL CHECK (verdict IN ('new', 'updated')),
    -- 이 팩트가 갱신한 과거 팩트. Diff worker가 찍은 updates_fact_id를 검증한 뒤
    -- 저장하며, before 문구는 이 링크로 DB에서 읽는다(LLM이 과거값을 다시 쓰지 못한다).
    supersedes_fact_id uuid REFERENCES agent.change_history_facts(id),
    -- 타임라인 절대 날짜. 반기·분기처럼 확정 불가한 표기는 해당 구간 첫날로
    -- 정규화하고 date_precision에 원래 정밀도를 남긴다.
    occurred_on date,
    date_precision text NOT NULL DEFAULT 'unknown'
        CHECK (date_precision IN ('day', 'month', 'quarter', 'half', 'year', 'unknown')),
    source_reference text,
    source_url text,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'superseded')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- search_base_facts 도구와 Base 조회는 항상 (user_id, topic) 소속의 active
-- 팩트만 본다. 다른 사용자·다른 토픽 팩트를 가리킨 오매칭은 조회에서 걸러진다.
CREATE INDEX IF NOT EXISTS ix_change_history_facts_scope
    ON agent.change_history_facts (user_id, topic, status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_change_history_facts_subject
    ON agent.change_history_facts (user_id, topic, subject, attribute);
-- 도구의 query 검색은 subject·attribute·statement를 trigram으로 훑는다
-- (임베딩·벡터스토어는 이 규모에 과설계라 쓰지 않는다).
CREATE INDEX IF NOT EXISTS ix_change_history_facts_search
    ON agent.change_history_facts USING gin (
        (subject || ' ' || attribute || ' ' || statement) gin_trgm_ops
    );

-- RLS 활성화는 이미 켜져 있어도 오류가 아니다.
ALTER TABLE agent.change_history_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.change_history_facts ENABLE ROW LEVEL SECURITY;

-- CREATE POLICY / CREATE TRIGGER 에는 IF NOT EXISTS 가 없어 DROP 선행으로 멱등화한다.
DROP POLICY IF EXISTS change_history_run_isolation ON agent.change_history_runs;
CREATE POLICY change_history_run_isolation ON agent.change_history_runs
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());
DROP POLICY IF EXISTS change_history_fact_isolation ON agent.change_history_facts;
CREATE POLICY change_history_fact_isolation ON agent.change_history_facts
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());

DROP TRIGGER IF EXISTS set_change_history_facts_updated_at ON agent.change_history_facts;
CREATE TRIGGER set_change_history_facts_updated_at
    BEFORE UPDATE ON agent.change_history_facts
    FOR EACH ROW EXECUTE FUNCTION agent.set_updated_at();

INSERT INTO agent.schema_migrations (version, description)
VALUES (15, 'Store change history delta facts and per-run delta metadata (reissue of duplicated 0012)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
