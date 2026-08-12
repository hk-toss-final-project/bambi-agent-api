-- 관심사 수집 대상을 실제 구독자 수에 맞춰 정리하고 하루 처리량을 250회로 제한한다.

BEGIN;

WITH subscription_counts AS (
    SELECT
        target.target_key,
        count(subscription.id)::integer AS subscriber_count
    FROM agent.interest_collection_targets AS target
    LEFT JOIN agent.user_interest_subscriptions AS subscription
      ON subscription.target_key = target.target_key
     AND subscription.active
    GROUP BY target.target_key
), base_policy AS (
    SELECT
        target.target_key,
        target.status,
        target.refresh_interval_minutes,
        counts.subscriber_count,
        CASE
            WHEN counts.subscriber_count >= 10 THEN 360
            WHEN counts.subscriber_count >= 5 THEN 720
            ELSE 1440
        END AS base_interval_minutes
    FROM agent.interest_collection_targets AS target
    JOIN subscription_counts AS counts
      ON counts.target_key = target.target_key
), capacity AS (
    SELECT GREATEST(
        1.0,
        COALESCE(
            SUM(1440.0 / base_interval_minutes)
                FILTER (WHERE status <> 'retired' AND subscriber_count > 0),
            0.0
        ) / 250.0
    ) AS scale
    FROM base_policy
), desired AS (
    SELECT
        policy.target_key,
        policy.subscriber_count,
        CASE
            WHEN policy.status = 'retired' THEN 'retired'
            WHEN policy.subscriber_count = 0 THEN 'paused'
            ELSE 'active'
        END AS status,
        CASE
            WHEN policy.status = 'retired' OR policy.subscriber_count = 0
            THEN policy.refresh_interval_minutes
            ELSE LEAST(
                10080,
                CEIL(policy.base_interval_minutes * capacity.scale)::integer
            )
        END AS refresh_interval_minutes
    FROM base_policy AS policy
    CROSS JOIN capacity
)
UPDATE agent.interest_collection_targets AS target
SET subscriber_count = desired.subscriber_count,
    status = desired.status,
    refresh_interval_minutes = desired.refresh_interval_minutes
FROM desired
WHERE desired.target_key = target.target_key
  AND (
      target.subscriber_count,
      target.status,
      target.refresh_interval_minutes
  ) IS DISTINCT FROM (
      desired.subscriber_count,
      desired.status,
      desired.refresh_interval_minutes
  );

INSERT INTO agent.schema_migrations (version, description)
VALUES (29, 'Reconcile interest collection targets within daily capacity');

COMMIT;
