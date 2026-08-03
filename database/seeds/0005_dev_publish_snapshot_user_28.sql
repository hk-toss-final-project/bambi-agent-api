-- Service Worker 발행 루프 관통 검증용 Publish Snapshot (사용자 28).
--
-- 기존 Seed(0001·0002)의 user_id는 'mock-user-001'처럼 문자열이라, 숫자 id를
-- 요구하는 service 워커가 Claim한 Snapshot을 실제 사용자와 연결하지 못했다.
-- 이 Seed는 service의 실제 사용자 id(28)와 카드 관심사 태그(tags)를 함께 갖는
-- Snapshot 한 건을 만들어 claim → reports/card 저장까지 흐르는지 확인하게 한다.
--
-- snapshot_hash는 애플리케이션과 같은 방식(sha256 of "title\nsummary\nbody")으로
-- 계산했다. 본문을 고치면 해시도 다시 계산해야 ACK 검증이 통과한다.
--
-- 2026-08-03 픽스: user_context_snapshots의 실제 유니크 키는 (user_id, context_version)이다
-- (0001_initial.sql). 사용자 28은 가입 시 service가 이미 (28, 1) 컨텍스트를 동기화해 두므로
-- 고정 id 기준 ON CONFLICT (id)로는 충돌을 못 잡아 duplicate key로 시드 전체가 실패했다
-- (07-30 이후 배포 빨간불의 원인). 실키 기준 DO NOTHING으로 바꾸고, 이미 존재하는(랜덤 id)
-- 실제 컨텍스트 행을 쓰도록 generation_requests의 참조를 서브쿼리로 조회한다.

\set ON_ERROR_STOP on

BEGIN;

SET LOCAL app.access_scope = 'system';

INSERT INTO agent.user_context_snapshots (
    id,
    user_id,
    context_version,
    plan,
    preferred_language,
    personalization_enabled,
    attributes
) VALUES (
    '10000000-0000-4000-8000-000000000028',
    '28',
    1,
    'free',
    'ko',
    true,
    '{"seed": true}'::jsonb
)
ON CONFLICT (user_id, context_version) DO NOTHING;

INSERT INTO agent.agent_jobs (
    id,
    feature_id,
    job_type,
    user_id,
    idempotency_key,
    status,
    progress,
    payload,
    result,
    request_id,
    started_at,
    completed_at
) VALUES (
    '20000000-0000-4000-8000-000000000028',
    'SVC-008',
    'report_generation',
    '28',
    'dev-generation-028',
    'completed',
    100,
    '{"topic":"환율","content_type":"interest_news_card","language":"ko"}'::jsonb,
    '{"content_id":"dev-content-028","version":1,"snapshot_hash":"1ef4abb48904334764da204f9a83c49714368063b73138dc7ead3c6db41a5201"}'::jsonb,
    'dev-request-028',
    '2026-07-30T00:00:00Z',
    '2026-07-30T00:00:01Z'
)
ON CONFLICT (id) DO UPDATE SET
    status = EXCLUDED.status,
    progress = EXCLUDED.progress,
    payload = EXCLUDED.payload,
    result = EXCLUDED.result,
    request_id = EXCLUDED.request_id,
    started_at = EXCLUDED.started_at,
    completed_at = EXCLUDED.completed_at,
    updated_at = clock_timestamp();

INSERT INTO agent.generation_requests (
    id,
    job_id,
    user_id,
    user_context_snapshot_id,
    topic,
    content_type,
    plan,
    language,
    status,
    parameters
) VALUES (
    '30000000-0000-4000-8000-000000000028',
    '20000000-0000-4000-8000-000000000028',
    '28',
    (SELECT id FROM agent.user_context_snapshots
      WHERE user_id = '28' AND context_version = 1),
    '환율',
    'interest_news_card',
    'free',
    'ko',
    'completed',
    '{"seed": true}'::jsonb
)
ON CONFLICT (id) DO UPDATE SET
    topic = EXCLUDED.topic,
    content_type = EXCLUDED.content_type,
    plan = EXCLUDED.plan,
    language = EXCLUDED.language,
    status = EXCLUDED.status,
    parameters = EXCLUDED.parameters,
    updated_at = clock_timestamp();

INSERT INTO agent.generation_runs (
    id,
    generation_request_id,
    user_id,
    attempt_number,
    status,
    input_tokens,
    output_tokens,
    estimated_cost,
    latency_ms,
    run_metadata,
    started_at,
    completed_at
) VALUES (
    '40000000-0000-4000-8000-000000000028',
    '30000000-0000-4000-8000-000000000028',
    '28',
    1,
    'completed',
    0,
    0,
    0,
    1000,
    '{"mode":"mock","seed":true}'::jsonb,
    '2026-07-30T00:00:00Z',
    '2026-07-30T00:00:01Z'
)
ON CONFLICT (id) DO UPDATE SET
    status = EXCLUDED.status,
    input_tokens = EXCLUDED.input_tokens,
    output_tokens = EXCLUDED.output_tokens,
    estimated_cost = EXCLUDED.estimated_cost,
    latency_ms = EXCLUDED.latency_ms,
    run_metadata = EXCLUDED.run_metadata,
    started_at = EXCLUDED.started_at,
    completed_at = EXCLUDED.completed_at;

INSERT INTO agent.generated_content_candidates (
    id,
    generation_request_id,
    generation_run_id,
    user_id,
    content_id,
    version,
    content_type,
    status,
    title,
    summary,
    body,
    structured_body,
    snapshot_hash,
    created_at,
    updated_at
) VALUES (
    '50000000-0000-4000-8000-000000000028',
    '30000000-0000-4000-8000-000000000028',
    '40000000-0000-4000-8000-000000000028',
    '28',
    'dev-content-028',
    1,
    'interest_news_card',
    'ready',
    '환율 급등, 수입 물가에 미치는 영향',
    '원/달러 환율이 단기간에 오르면서 수입 물가와 기업 원가 부담이 함께 커지고 있습니다.',
    '원/달러 환율 상승은 수입 원자재 가격을 끌어올려 제조업 원가에 직접 반영됩니다[G1]. 특히 에너지와 곡물처럼 달러로 결제하는 품목은 환율 변동이 소비자 물가로 이어지는 시차가 짧습니다[G2]. 이 콘텐츠는 Service Worker 발행 루프 연동 검증을 위한 개발용 목업 본문입니다.',
    '{"format":"markdown"}'::jsonb,
    '1ef4abb48904334764da204f9a83c49714368063b73138dc7ead3c6db41a5201',
    '2026-07-30T00:00:01Z',
    '2026-07-30T00:00:01Z'
)
ON CONFLICT (id) DO UPDATE SET
    status = EXCLUDED.status,
    title = EXCLUDED.title,
    summary = EXCLUDED.summary,
    body = EXCLUDED.body,
    structured_body = EXCLUDED.structured_body,
    snapshot_hash = EXCLUDED.snapshot_hash,
    updated_at = EXCLUDED.updated_at;

INSERT INTO agent.citations (
    id,
    candidate_id,
    user_id,
    ordinal,
    title,
    url,
    quoted_text,
    claim_paths
) VALUES
    (
        '70000000-0000-4000-8000-000000000028',
        '50000000-0000-4000-8000-000000000028',
        '28',
        0,
        '환율 상승과 수입 물가 (개발용 목업 출처)',
        'https://example.com/dev-fx-import-price',
        '환율 상승이 수입 원자재 가격에 반영되는 경로를 설명한 목업 출처입니다.',
        ARRAY['body']::text[]
    ),
    (
        '70000000-0000-4000-8000-000000000029',
        '50000000-0000-4000-8000-000000000028',
        '28',
        1,
        '에너지·곡물 결제 통화 (개발용 목업 출처)',
        'https://example.com/dev-fx-energy-grain',
        '달러 결제 품목의 물가 전가 시차를 설명한 목업 출처입니다.',
        ARRAY['body']::text[]
    )
ON CONFLICT (id) DO UPDATE SET
    title = EXCLUDED.title,
    url = EXCLUDED.url,
    quoted_text = EXCLUDED.quoted_text,
    claim_paths = EXCLUDED.claim_paths;

INSERT INTO agent.publish_snapshots (
    id,
    candidate_id,
    user_id,
    content_id,
    version,
    snapshot_hash,
    payload,
    status,
    created_at,
    acknowledged_at,
    failure_reason
) VALUES (
    '60000000-0000-4000-8000-000000000028',
    '50000000-0000-4000-8000-000000000028',
    '28',
    'dev-content-028',
    1,
    '1ef4abb48904334764da204f9a83c49714368063b73138dc7ead3c6db41a5201',
    '{
      "title":"환율 급등, 수입 물가에 미치는 영향",
      "summary":"원/달러 환율이 단기간에 오르면서 수입 물가와 기업 원가 부담이 함께 커지고 있습니다.",
      "body":"원/달러 환율 상승은 수입 원자재 가격을 끌어올려 제조업 원가에 직접 반영됩니다[G1]. 특히 에너지와 곡물처럼 달러로 결제하는 품목은 환율 변동이 소비자 물가로 이어지는 시차가 짧습니다[G2]. 이 콘텐츠는 Service Worker 발행 루프 연동 검증을 위한 개발용 목업 본문입니다.",
      "citations":[
        {
          "citation_id":"70000000-0000-4000-8000-000000000028",
          "title":"환율 상승과 수입 물가 (개발용 목업 출처)",
          "url":"https://example.com/dev-fx-import-price"
        },
        {
          "citation_id":"70000000-0000-4000-8000-000000000029",
          "title":"에너지·곡물 결제 통화 (개발용 목업 출처)",
          "url":"https://example.com/dev-fx-energy-grain"
        }
      ],
      "tags":["환율"]
    }'::jsonb,
    'ready',
    '2026-07-30T00:00:01Z',
    NULL,
    NULL
)
ON CONFLICT (id) DO UPDATE SET
    candidate_id = EXCLUDED.candidate_id,
    user_id = EXCLUDED.user_id,
    content_id = EXCLUDED.content_id,
    version = EXCLUDED.version,
    snapshot_hash = EXCLUDED.snapshot_hash,
    payload = EXCLUDED.payload,
    status = EXCLUDED.status,
    created_at = EXCLUDED.created_at,
    acknowledged_at = NULL,
    failure_reason = NULL;

COMMIT;
