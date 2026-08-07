-- 변경점(Delta) 추적 에이전트가 실행마다 추출한 팩트와 실행 메타를 저장한다.
-- 이 테이블은 "출력"이 아니라 다음 실행의 Base 재료다. publish_snapshots는
-- Markdown 본문뿐이라 팩트 단위 대조에 쓸 수 없어서 별도 저장소를 둔다.
-- 기존 테이블은 변경하지 않는 순수 additive Migration이다.
--
-- 2026-08-07 재발행: 원래 0012 였는데 0012_global_source_search_body.sql 과 번호가
-- 겹쳐 러너가 조용히 건너뛰었다(운영에 한 번도 적용되지 않았다). 내용은 그대로 두고
-- 파일명과 기록 version 만 15 로 옮겼다.

\set ON_ERROR_STOP on

BEGIN;

-- 한 번의 변경점 추적 실행. "직전 보고서 시점"을 날짜가 아니라 이 실행 기록으로
-- 잡는다(매일 돌지 않아도 델타가 끊기지 않게 한다).
CREATE TABLE agent.change_history_runs (
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

CREATE INDEX ix_change_history_runs_latest
    ON agent.change_history_runs (user_id, topic, created_at DESC);

-- 팩트 하나 = (subject, attribute, fact_value) 세 요소. 중복·갱신 판정은
-- (subject, attribute) 매칭으로 하고, fact_value가 다르면 갱신으로 본다.
CREATE TABLE agent.change_history_facts (
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
CREATE INDEX ix_change_history_facts_scope
    ON agent.change_history_facts (user_id, topic, status, created_at DESC);
CREATE INDEX ix_change_history_facts_subject
    ON agent.change_history_facts (user_id, topic, subject, attribute);
-- 도구의 query 검색은 subject·attribute·statement를 trigram으로 훑는다
-- (임베딩·벡터스토어는 이 규모에 과설계라 쓰지 않는다).
CREATE INDEX ix_change_history_facts_search
    ON agent.change_history_facts USING gin (
        (subject || ' ' || attribute || ' ' || statement) gin_trgm_ops
    );

ALTER TABLE agent.change_history_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.change_history_facts ENABLE ROW LEVEL SECURITY;

CREATE POLICY change_history_run_isolation ON agent.change_history_runs
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());
CREATE POLICY change_history_fact_isolation ON agent.change_history_facts
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());

CREATE TRIGGER set_change_history_facts_updated_at
    BEFORE UPDATE ON agent.change_history_facts
    FOR EACH ROW EXECUTE FUNCTION agent.set_updated_at();

INSERT INTO agent.schema_migrations (version, description)
VALUES (15, 'Store change history delta facts and per-run delta metadata');

COMMIT;
