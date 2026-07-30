-- Service Worker API 로컬 연동을 위한 결정적 Publish Snapshot 목업 데이터.

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
    '10000000-0000-4000-8000-000000000001',
    'mock-user-001',
    1,
    'free',
    'ko',
    true,
    '{"seed": true}'::jsonb
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
) VALUES (
    '20000000-0000-4000-8000-000000000001',
    'SVC-008',
    'report_generation',
    'mock-user-001',
    'mock-generation-001',
    'completed',
    100,
    '{"topic":"AI 에이전트 동향","content_type":"interest_news_card","language":"ko"}'::jsonb,
    '{"content_id":"mock-content-001","version":1,"snapshot_hash":"d3b07384d113edec49eaa6238ad5ff00d3b07384d113edec49eaa6238ad5ff00"}'::jsonb,
    'mock-request-001',
    '2026-07-13T00:00:00Z',
    '2026-07-13T00:00:01Z'
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
    '30000000-0000-4000-8000-000000000001',
    '20000000-0000-4000-8000-000000000001',
    'mock-user-001',
    '10000000-0000-4000-8000-000000000001',
    'AI 에이전트 동향',
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
    '40000000-0000-4000-8000-000000000001',
    '30000000-0000-4000-8000-000000000001',
    'mock-user-001',
    1,
    'completed',
    0,
    0,
    0,
    1000,
    '{"mode":"mock","seed":true}'::jsonb,
    '2026-07-13T00:00:00Z',
    '2026-07-13T00:00:01Z'
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
    '50000000-0000-4000-8000-000000000001',
    '30000000-0000-4000-8000-000000000001',
    '40000000-0000-4000-8000-000000000001',
    'mock-user-001',
    'mock-content-001',
    1,
    'interest_news_card',
    'ready',
    'AI 에이전트, 일상 도구로 확장',
    'AI 에이전트가 업무 자동화를 넘어 개인의 일상 도구로 확장되고 있습니다.',
    '최근 AI 에이전트는 검색과 요약뿐 아니라 여러 도구를 연결해 사용자의 목표를 수행하는 방향으로 발전하고 있습니다. 이 콘텐츠는 Service Worker API 연동 검증을 위한 목업 본문입니다.',
    '{"sections":[{"type":"paragraph","text":"Service Worker 연동용 목업 콘텐츠입니다."}]}'::jsonb,
    'd3b07384d113edec49eaa6238ad5ff00d3b07384d113edec49eaa6238ad5ff00',
    '2026-07-13T00:00:01Z',
    '2026-07-13T00:00:01Z'
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
) VALUES (
    '70000000-0000-4000-8000-000000000001',
    '50000000-0000-4000-8000-000000000001',
    'mock-user-001',
    0,
    'Report Builder Agent API 목업 출처',
    'https://example.com/mock-ai-agent',
    'Service Worker 연동 검증을 위한 목업 출처입니다.',
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
    '60000000-0000-4000-8000-000000000001',
    '50000000-0000-4000-8000-000000000001',
    'mock-user-001',
    'mock-content-001',
    1,
    'd3b07384d113edec49eaa6238ad5ff00d3b07384d113edec49eaa6238ad5ff00',
    '{
      "title":"AI 에이전트, 일상 도구로 확장",
      "summary":"AI 에이전트가 업무 자동화를 넘어 개인의 일상 도구로 확장되고 있습니다.",
      "body":"최근 AI 에이전트는 검색과 요약뿐 아니라 여러 도구를 연결해 사용자의 목표를 수행하는 방향으로 발전하고 있습니다. 이 콘텐츠는 Service Worker API 연동 검증을 위한 목업 본문입니다.",
      "citations":[{
        "citation_id":"70000000-0000-4000-8000-000000000001",
        "title":"Report Builder Agent API 목업 출처",
        "url":"https://example.com/mock-ai-agent"
      }],
      "tags":["AI 에이전트 동향"]
    }'::jsonb,
    'ready',
    '2026-07-13T00:00:01Z',
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
