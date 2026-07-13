-- Batch Claim 검증을 위한 두 건의 독립적인 Publish Snapshot 목업 데이터를 추가한다.

\set ON_ERROR_STOP on

BEGIN;

SET LOCAL app.access_scope = 'system';

DELETE FROM agent.publish_attempts
WHERE snapshot_id IN (
    '60000000-0000-4000-8000-000000000001',
    '60000000-0000-4000-8000-000000000002',
    '60000000-0000-4000-8000-000000000003'
);

INSERT INTO agent.user_context_snapshots (
    id,
    user_id,
    context_version,
    plan,
    preferred_language,
    personalization_enabled,
    attributes
) VALUES
    (
        '10000000-0000-4000-8000-000000000002',
        'mock-user-002',
        1,
        'paid',
        'ko',
        true,
        '{"seed":true,"interests":["on-device-ai","mobile"]}'::jsonb
    ),
    (
        '10000000-0000-4000-8000-000000000003',
        'mock-user-003',
        1,
        'free',
        'ko',
        true,
        '{"seed":true,"interests":["green-tech","data-center"]}'::jsonb
    )
ON CONFLICT (id) DO UPDATE SET
    plan = EXCLUDED.plan,
    preferred_language = EXCLUDED.preferred_language,
    personalization_enabled = EXCLUDED.personalization_enabled,
    attributes = EXCLUDED.attributes;

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
) VALUES
    (
        '20000000-0000-4000-8000-000000000002',
        'SVC-008',
        'bambi_generation',
        'mock-user-002',
        'mock-generation-002',
        'completed',
        100,
        '{"topic":"온디바이스 AI","content_type":"interest_news_card","language":"ko"}'::jsonb,
        '{"content_id":"mock-content-002","version":1,"snapshot_hash":"4e07408562bedb8b60ce05c1decfe3ad16b72230967de01f640b7e4729b49fce"}'::jsonb,
        'mock-request-002',
        '2026-07-13T00:00:01Z',
        '2026-07-13T00:00:02Z'
    ),
    (
        '20000000-0000-4000-8000-000000000003',
        'SVC-008',
        'bambi_generation',
        'mock-user-003',
        'mock-generation-003',
        'completed',
        100,
        '{"topic":"친환경 데이터센터","content_type":"interest_news_card","language":"ko"}'::jsonb,
        '{"content_id":"mock-content-003","version":1,"snapshot_hash":"4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a"}'::jsonb,
        'mock-request-003',
        '2026-07-13T00:00:02Z',
        '2026-07-13T00:00:03Z'
    )
ON CONFLICT (id) DO UPDATE SET
    status = EXCLUDED.status,
    progress = EXCLUDED.progress,
    payload = EXCLUDED.payload,
    result = EXCLUDED.result,
    request_id = EXCLUDED.request_id,
    started_at = EXCLUDED.started_at,
    completed_at = EXCLUDED.completed_at,
    lease_expires_at = NULL,
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
) VALUES
    (
        '30000000-0000-4000-8000-000000000002',
        '20000000-0000-4000-8000-000000000002',
        'mock-user-002',
        '10000000-0000-4000-8000-000000000002',
        '온디바이스 AI',
        'interest_news_card',
        'paid',
        'ko',
        'completed',
        '{"seed":true}'::jsonb
    ),
    (
        '30000000-0000-4000-8000-000000000003',
        '20000000-0000-4000-8000-000000000003',
        'mock-user-003',
        '10000000-0000-4000-8000-000000000003',
        '친환경 데이터센터',
        'interest_news_card',
        'free',
        'ko',
        'completed',
        '{"seed":true}'::jsonb
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
) VALUES
    (
        '40000000-0000-4000-8000-000000000002',
        '30000000-0000-4000-8000-000000000002',
        'mock-user-002',
        1,
        'completed',
        0,
        0,
        0,
        1100,
        '{"mode":"mock","seed":true}'::jsonb,
        '2026-07-13T00:00:01Z',
        '2026-07-13T00:00:02Z'
    ),
    (
        '40000000-0000-4000-8000-000000000003',
        '30000000-0000-4000-8000-000000000003',
        'mock-user-003',
        1,
        'completed',
        0,
        0,
        0,
        1200,
        '{"mode":"mock","seed":true}'::jsonb,
        '2026-07-13T00:00:02Z',
        '2026-07-13T00:00:03Z'
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
) VALUES
    (
        '50000000-0000-4000-8000-000000000002',
        '30000000-0000-4000-8000-000000000002',
        '40000000-0000-4000-8000-000000000002',
        'mock-user-002',
        'mock-content-002',
        1,
        'interest_news_card',
        'ready',
        '온디바이스 AI가 바꾸는 모바일 경험',
        '스마트폰 안에서 동작하는 AI가 응답 속도와 개인정보 보호를 함께 개선합니다.',
        '온디바이스 AI는 주요 연산을 기기 내부에서 처리해 네트워크 지연을 줄이고 민감한 데이터의 외부 전송을 최소화합니다. 이 콘텐츠는 Batch API 검증을 위한 목업 본문입니다.',
        '{"sections":[{"type":"paragraph","text":"온디바이스 AI 목업 콘텐츠입니다."}]}'::jsonb,
        '4e07408562bedb8b60ce05c1decfe3ad16b72230967de01f640b7e4729b49fce',
        '2026-07-13T00:00:02Z',
        '2026-07-13T00:00:02Z'
    ),
    (
        '50000000-0000-4000-8000-000000000003',
        '30000000-0000-4000-8000-000000000003',
        '40000000-0000-4000-8000-000000000003',
        'mock-user-003',
        'mock-content-003',
        1,
        'interest_news_card',
        'ready',
        '데이터센터의 전력 효율 경쟁',
        'AI 인프라 확대로 데이터센터의 냉각과 재생에너지 활용이 중요해지고 있습니다.',
        '데이터센터 운영사는 고효율 냉각 기술과 재생에너지 조달을 결합해 전력 사용량과 탄소 배출을 낮추고 있습니다. 이 콘텐츠는 Batch API 검증을 위한 목업 본문입니다.',
        '{"sections":[{"type":"paragraph","text":"친환경 데이터센터 목업 콘텐츠입니다."}]}'::jsonb,
        '4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a',
        '2026-07-13T00:00:03Z',
        '2026-07-13T00:00:03Z'
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
        '70000000-0000-4000-8000-000000000002',
        '50000000-0000-4000-8000-000000000002',
        'mock-user-002',
        0,
        '온디바이스 AI 목업 출처',
        'https://example.com/mock-on-device-ai',
        'Batch API 검증을 위한 온디바이스 AI 목업 출처입니다.',
        ARRAY['body']::text[]
    ),
    (
        '70000000-0000-4000-8000-000000000003',
        '50000000-0000-4000-8000-000000000003',
        'mock-user-003',
        0,
        '친환경 데이터센터 목업 출처',
        'https://example.com/mock-green-data-center',
        'Batch API 검증을 위한 친환경 데이터센터 목업 출처입니다.',
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
    created_at
) VALUES
    (
        '60000000-0000-4000-8000-000000000002',
        '50000000-0000-4000-8000-000000000002',
        'mock-user-002',
        'mock-content-002',
        1,
        '4e07408562bedb8b60ce05c1decfe3ad16b72230967de01f640b7e4729b49fce',
        '{
          "title":"온디바이스 AI가 바꾸는 모바일 경험",
          "summary":"스마트폰 안에서 동작하는 AI가 응답 속도와 개인정보 보호를 함께 개선합니다.",
          "body":"온디바이스 AI는 주요 연산을 기기 내부에서 처리해 네트워크 지연을 줄이고 민감한 데이터의 외부 전송을 최소화합니다. 이 콘텐츠는 Batch API 검증을 위한 목업 본문입니다.",
          "citations":[{
            "citation_id":"70000000-0000-4000-8000-000000000002",
            "title":"온디바이스 AI 목업 출처",
            "url":"https://example.com/mock-on-device-ai"
          }]
        }'::jsonb,
        'ready',
        '2026-07-13T00:00:02Z'
    ),
    (
        '60000000-0000-4000-8000-000000000003',
        '50000000-0000-4000-8000-000000000003',
        'mock-user-003',
        'mock-content-003',
        1,
        '4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a',
        '{
          "title":"데이터센터의 전력 효율 경쟁",
          "summary":"AI 인프라 확대로 데이터센터의 냉각과 재생에너지 활용이 중요해지고 있습니다.",
          "body":"데이터센터 운영사는 고효율 냉각 기술과 재생에너지 조달을 결합해 전력 사용량과 탄소 배출을 낮추고 있습니다. 이 콘텐츠는 Batch API 검증을 위한 목업 본문입니다.",
          "citations":[{
            "citation_id":"70000000-0000-4000-8000-000000000003",
            "title":"친환경 데이터센터 목업 출처",
            "url":"https://example.com/mock-green-data-center"
          }]
        }'::jsonb,
        'ready',
        '2026-07-13T00:00:03Z'
    )
ON CONFLICT (id) DO UPDATE SET
    candidate_id = EXCLUDED.candidate_id,
    user_id = EXCLUDED.user_id,
    content_id = EXCLUDED.content_id,
    version = EXCLUDED.version,
    snapshot_hash = EXCLUDED.snapshot_hash,
    payload = EXCLUDED.payload,
    status = EXCLUDED.status,
    created_at = EXCLUDED.created_at;

UPDATE agent.publish_snapshots
SET
    status = 'ready',
    claim_id = NULL,
    claimed_by = NULL,
    lease_expires_at = NULL,
    attempt_count = 0,
    next_attempt_at = NULL,
    acknowledged_at = NULL,
    failure_reason = NULL
WHERE id IN (
    '60000000-0000-4000-8000-000000000001',
    '60000000-0000-4000-8000-000000000002',
    '60000000-0000-4000-8000-000000000003'
);

COMMIT;
