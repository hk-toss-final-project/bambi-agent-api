-- 아침 브리핑 주제 선정 결과를 보관해 같은 아침에 두 번 뽑지 않게 한다.
--
-- Service는 03:00에 주제를 미리 물어 그 주제로 창고 수집을 걸고, 07:00에 같은
-- 엔드포인트를 다시 부른다. 두 호출이 다른 주제를 돌려주면 새벽에 모아둔 자료가
-- 그 주제와 맞지 않아 사전 수집이 헛돈다.
--
-- 유효성은 시간이 아니라 `candidate_digest`로 판단한다. 주제 선정은 뉴스가 아니라
-- 개인 Wiki 후보에서 나오므로, 후보가 그대로면 몇 시간이 지나도 같은 답이 맞다.
-- 반대로 밤사이 클리퍼로 글을 저장해 후보가 달라지면 재사용하면 안 된다.

\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE agent.briefing_topic_selections (
    user_id text PRIMARY KEY,
    -- 선정에 쓴 후보 목록의 지문. 이 값이 같으면 같은 답이 나온다.
    candidate_digest text NOT NULL,
    -- 고른 주제. 순서가 의미를 가지므로 배열로 둔다.
    topics text[] NOT NULL,
    reason text NOT NULL DEFAULT '',
    candidate_count integer NOT NULL DEFAULT 0
        CHECK (candidate_count >= 0),
    -- 고른 주제 수 상한(요청 limit). 요청이 3개인데 2개로 저장된 결과를
    -- 그대로 돌려주면 계약이 깨지므로 함께 보관해 대조한다.
    topic_limit integer NOT NULL
        CHECK (topic_limit BETWEEN 1 AND 5),
    selected_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

COMMENT ON TABLE agent.briefing_topic_selections IS
    '03:00 선조회 결과를 07:00 호출에서 재사용하기 위한 아침 주제 선정 캐시';
COMMENT ON COLUMN agent.briefing_topic_selections.candidate_digest IS
    '선정 입력이 된 Wiki 후보 목록의 SHA-256 지문. 달라지면 재선정한다';

ALTER TABLE agent.briefing_topic_selections ENABLE ROW LEVEL SECURITY;

CREATE POLICY briefing_topic_selection_read ON agent.briefing_topic_selections
    FOR SELECT
    USING (
        agent.has_system_scope()
        OR user_id = agent.current_user_id()
    );

CREATE POLICY briefing_topic_selection_write ON agent.briefing_topic_selections
    FOR ALL
    USING (
        agent.has_system_scope()
        OR user_id = agent.current_user_id()
    )
    WITH CHECK (
        agent.has_system_scope()
        OR user_id = agent.current_user_id()
    );

INSERT INTO agent.schema_migrations (version, description)
VALUES (27, 'Cache morning briefing topic selections for 03:00 prefetch reuse');

COMMIT;
