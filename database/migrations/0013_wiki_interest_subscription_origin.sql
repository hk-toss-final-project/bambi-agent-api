-- 구독이 어디서 왔는지 구분한다.
--
-- 지금까지 user_interest_subscriptions는 온보딩 컨텍스트에서만 만들어졌고,
-- 컨텍스트를 저장할 때마다 그 사용자의 구독을 전부 비활성화한 뒤 다시 넣는다.
-- 여기에 개인 Wiki 관심사에서 자동 등록한 구독을 섞으면, 다음 컨텍스트 저장에
-- 함께 지워진다. origin으로 나눠 각자 자기 몫만 비활성화하게 한다.
--
--   onboarding    사용자가 온보딩에서 고른 Topic (기존 동작)
--   wiki_interest 개인 Wiki 관심사 상위 Topic을 자동 등록한 것
--
-- 기존 행은 전부 온보딩에서 온 것이므로 기본값이 그대로 맞다.

BEGIN;

ALTER TABLE agent.user_interest_subscriptions
    ADD COLUMN IF NOT EXISTS origin text NOT NULL DEFAULT 'onboarding';

ALTER TABLE agent.user_interest_subscriptions
    DROP CONSTRAINT IF EXISTS user_interest_subscriptions_origin_check;

ALTER TABLE agent.user_interest_subscriptions
    ADD CONSTRAINT user_interest_subscriptions_origin_check
    CHECK (origin IN ('onboarding', 'wiki_interest'));

-- 출처별로 자기 구독만 훑어 비활성화하므로 (user_id, origin, active)로 찾는다.
CREATE INDEX IF NOT EXISTS ix_user_interest_subscriptions_origin
    ON agent.user_interest_subscriptions (user_id, origin)
    WHERE active;

INSERT INTO agent.schema_migrations (version, description)
VALUES (13, '개인 Wiki 관심사 자동 구독을 온보딩 구독과 구분하는 origin 컬럼')
ON CONFLICT (version) DO NOTHING;

COMMIT;
