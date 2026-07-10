-- Bambi Agent DB의 PostgreSQL 17 초기 스키마를 생성한다.

\set ON_ERROR_STOP on

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE SCHEMA agent;
REVOKE ALL ON SCHEMA agent FROM PUBLIC;

CREATE FUNCTION agent.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, agent
AS $$
BEGIN
    NEW.updated_at = clock_timestamp();
    RETURN NEW;
END;
$$;

CREATE FUNCTION agent.current_user_id()
RETURNS text
LANGUAGE sql
STABLE
SET search_path = pg_catalog
AS $$
    SELECT NULLIF(current_setting('app.user_id', true), '');
$$;

CREATE FUNCTION agent.has_system_scope()
RETURNS boolean
LANGUAGE sql
STABLE
SET search_path = pg_catalog
AS $$
    SELECT current_setting('app.access_scope', true) = 'system';
$$;

-- DB-022: Prompt Template과 불변 버전을 관리한다.
CREATE TABLE agent.prompt_templates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_key text NOT NULL UNIQUE,
    description text,
    task_type text NOT NULL,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive', 'deleted')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE agent.prompt_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id uuid NOT NULL REFERENCES agent.prompt_templates(id),
    version integer NOT NULL CHECK (version > 0),
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'retired')),
    system_prompt text NOT NULL,
    user_prompt_template text,
    input_schema jsonb NOT NULL DEFAULT '{}'::jsonb,
    output_schema jsonb NOT NULL DEFAULT '{}'::jsonb,
    checksum text NOT NULL CHECK (length(checksum) = 64),
    change_reason text,
    created_by text,
    activated_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (template_id, version)
);

CREATE UNIQUE INDEX uq_prompt_versions_active
    ON agent.prompt_versions (template_id)
    WHERE status = 'active';

-- DB-023: Provider 및 작업·플랜별 Model Config 버전을 관리한다.
CREATE TABLE agent.model_configs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    config_key text NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    task_type text NOT NULL,
    plan text CHECK (plan IS NULL OR plan IN ('free', 'paid')),
    provider text NOT NULL,
    model_name text NOT NULL,
    parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
    fallback_order jsonb NOT NULL DEFAULT '[]'::jsonb,
    input_cost_per_million numeric(14, 6) CHECK (input_cost_per_million >= 0),
    output_cost_per_million numeric(14, 6) CHECK (output_cost_per_million >= 0),
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'retired')),
    created_by text,
    change_reason text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (config_key, version)
);

CREATE UNIQUE INDEX uq_model_configs_active
    ON agent.model_configs (config_key, COALESCE(plan, 'all'))
    WHERE status = 'active';

-- DB-024: Hybrid Search와 Reranking 정책 버전을 관리한다.
CREATE TABLE agent.retrieval_configs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    config_key text NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    plan text CHECK (plan IS NULL OR plan IN ('free', 'paid')),
    keyword_weight numeric(5, 4) NOT NULL DEFAULT 0.35
        CHECK (keyword_weight BETWEEN 0 AND 1),
    vector_weight numeric(5, 4) NOT NULL DEFAULT 0.65
        CHECK (vector_weight BETWEEN 0 AND 1),
    top_k integer NOT NULL DEFAULT 10 CHECK (top_k BETWEEN 1 AND 200),
    similarity_threshold numeric(5, 4)
        CHECK (similarity_threshold IS NULL OR similarity_threshold BETWEEN 0 AND 1),
    reranking jsonb NOT NULL DEFAULT '{}'::jsonb,
    chunk_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
    citation_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'retired')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (config_key, version)
);

CREATE UNIQUE INDEX uq_retrieval_configs_active
    ON agent.retrieval_configs (config_key, COALESCE(plan, 'all'))
    WHERE status = 'active';

-- DB-025: Embedding 모델과 차원 정책 버전을 관리한다.
CREATE TABLE agent.embedding_configs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    config_key text NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    provider text NOT NULL,
    model_name text NOT NULL,
    dimensions integer NOT NULL DEFAULT 1536 CHECK (dimensions = 1536),
    distance_metric text NOT NULL DEFAULT 'cosine'
        CHECK (distance_metric IN ('cosine', 'l2', 'inner_product')),
    chunk_policy_version text NOT NULL,
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'retired')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (config_key, version)
);

CREATE UNIQUE INDEX uq_embedding_configs_active
    ON agent.embedding_configs (config_key)
    WHERE status = 'active';

-- DB-001: Service 원본을 복제하지 않고 AI에 필요한 최소 컨텍스트만 버전별 저장한다.
CREATE TABLE agent.user_context_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL,
    context_version bigint NOT NULL CHECK (context_version > 0),
    plan text NOT NULL CHECK (plan IN ('free', 'paid')),
    preferred_language text NOT NULL DEFAULT 'ko',
    personalization_enabled boolean NOT NULL DEFAULT true,
    blocked_interest_ids text[] NOT NULL DEFAULT '{}',
    blocked_source_ids text[] NOT NULL DEFAULT '{}',
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
    checksum text CHECK (checksum IS NULL OR length(checksum) = 64),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    deleted_at timestamptz,
    UNIQUE (user_id, context_version)
);

CREATE INDEX ix_user_context_snapshots_latest
    ON agent.user_context_snapshots (user_id, context_version DESC)
    WHERE deleted_at IS NULL;

-- DB-026: API, Scheduler와 Worker가 공유하는 비동기 Agent Job 상태를 저장한다.
CREATE TABLE agent.agent_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    feature_id text NOT NULL,
    job_type text NOT NULL,
    user_id text,
    idempotency_key text NOT NULL,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'dead_letter')),
    priority smallint NOT NULL DEFAULT 100 CHECK (priority BETWEEN 0 AND 1000),
    progress smallint NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    result jsonb,
    result_version integer NOT NULL DEFAULT 1 CHECK (result_version > 0),
    error_code text,
    error_message text,
    retryable boolean NOT NULL DEFAULT false,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    queue_message_id text,
    request_id text,
    trace_id text,
    scheduled_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    locked_at timestamptz,
    locked_by text,
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (attempt_count <= max_attempts),
    CHECK (status <> 'completed' OR completed_at IS NOT NULL)
);

CREATE UNIQUE INDEX uq_agent_jobs_idempotency
    ON agent.agent_jobs (feature_id, COALESCE(user_id, ''), idempotency_key);
CREATE INDEX ix_agent_jobs_dequeue
    ON agent.agent_jobs (priority, scheduled_at, created_at)
    WHERE status = 'queued';
CREATE INDEX ix_agent_jobs_user_created
    ON agent.agent_jobs (user_id, created_at DESC)
    WHERE user_id IS NOT NULL;

CREATE TABLE agent.agent_job_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id uuid NOT NULL REFERENCES agent.agent_jobs(id) ON DELETE CASCADE,
    user_id text,
    attempt_number integer NOT NULL CHECK (attempt_number > 0),
    worker_id text NOT NULL,
    status text NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'timed_out')),
    error_code text,
    error_message text,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    UNIQUE (job_id, attempt_number)
);

-- DB-002: 개인 Wiki 편입 원천 이벤트와 멱등 처리 상태를 저장한다.
CREATE TABLE agent.wiki_source_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL,
    source_event_id text NOT NULL,
    source_type text NOT NULL
        CHECK (source_type IN ('web_clipping', 'url', 'content_mark', 'content_save', 'memo', 'edit', 'conversation', 'feedback', 'delete', 'rebuild')),
    job_id uuid REFERENCES agent.agent_jobs(id),
    occurred_at timestamptz,
    source_url text,
    source_content_id text,
    object_uri text,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'received'
        CHECK (status IN ('received', 'processing', 'completed', 'failed', 'ignored')),
    retry_count integer NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    error_code text,
    error_message text,
    processed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (user_id, source_event_id)
);

CREATE INDEX ix_wiki_source_events_status
    ON agent.wiki_source_events (status, created_at);

-- DB-003, DB-010: Personal과 Global 지식을 동일 구조에서 명시적으로 격리한다.
CREATE TABLE agent.wiki_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_scope text NOT NULL CHECK (knowledge_scope IN ('personal', 'global')),
    namespace_key text NOT NULL,
    user_id text,
    source_event_id uuid REFERENCES agent.wiki_source_events(id),
    source_type text NOT NULL,
    canonical_url text,
    language text NOT NULL DEFAULT 'und',
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'deleted', 'archived', 'superseded')),
    current_version integer NOT NULL DEFAULT 1 CHECK (current_version > 0),
    content_hash text NOT NULL CHECK (length(content_hash) = 64),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    deleted_at timestamptz,
    UNIQUE (id, namespace_key),
    CHECK (
        (knowledge_scope = 'global' AND user_id IS NULL AND namespace_key = 'global')
        OR
        (knowledge_scope = 'personal' AND user_id IS NOT NULL AND namespace_key = 'user/' || user_id)
    )
);

CREATE UNIQUE INDEX uq_wiki_documents_content
    ON agent.wiki_documents (namespace_key, content_hash)
    WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_wiki_documents_url
    ON agent.wiki_documents (namespace_key, canonical_url)
    WHERE canonical_url IS NOT NULL AND deleted_at IS NULL;
CREATE INDEX ix_wiki_documents_scope_updated
    ON agent.wiki_documents (namespace_key, updated_at DESC)
    WHERE deleted_at IS NULL;

CREATE TABLE agent.wiki_document_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL,
    namespace_key text NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    title text NOT NULL,
    summary text,
    normalized_content text,
    content_hash text NOT NULL CHECK (length(content_hash) = 64),
    object_uri text,
    source_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by_job_id uuid REFERENCES agent.agent_jobs(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (document_id, version),
    UNIQUE (id, namespace_key),
    FOREIGN KEY (document_id, namespace_key)
        REFERENCES agent.wiki_documents(id, namespace_key) ON DELETE CASCADE,
    CHECK (normalized_content IS NOT NULL OR object_uri IS NOT NULL)
);

-- DB-004, DB-011: 문서 버전에 연결된 검색 단위와 다국어 검색 인덱스를 저장한다.
CREATE TABLE agent.wiki_chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id uuid NOT NULL,
    namespace_key text NOT NULL,
    chunk_index integer NOT NULL CHECK (chunk_index >= 0),
    content text NOT NULL,
    token_count integer CHECK (token_count IS NULL OR token_count >= 0),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_searchable boolean NOT NULL DEFAULT true,
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (document_version_id, chunk_index),
    UNIQUE (id, namespace_key),
    FOREIGN KEY (document_version_id, namespace_key)
        REFERENCES agent.wiki_document_versions(id, namespace_key) ON DELETE CASCADE
);

CREATE INDEX ix_wiki_chunks_namespace
    ON agent.wiki_chunks (namespace_key, document_version_id)
    WHERE is_searchable;
CREATE INDEX ix_wiki_chunks_search_vector
    ON agent.wiki_chunks USING gin (search_vector)
    WHERE is_searchable;
CREATE INDEX ix_wiki_chunks_content_trgm
    ON agent.wiki_chunks USING gin (content gin_trgm_ops)
    WHERE is_searchable;

-- DB-005, DB-012: MVP 표준 1536차원 Embedding과 HNSW 검색 인덱스를 저장한다.
CREATE TABLE agent.wiki_embeddings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id uuid NOT NULL,
    namespace_key text NOT NULL,
    embedding_config_id uuid NOT NULL REFERENCES agent.embedding_configs(id),
    model_name text NOT NULL,
    model_version text NOT NULL,
    embedding vector(1536) NOT NULL,
    content_hash text NOT NULL CHECK (length(content_hash) = 64),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (chunk_id, embedding_config_id),
    FOREIGN KEY (chunk_id, namespace_key)
        REFERENCES agent.wiki_chunks(id, namespace_key) ON DELETE CASCADE
);

CREATE INDEX ix_wiki_embeddings_namespace
    ON agent.wiki_embeddings (namespace_key, chunk_id);
CREATE INDEX ix_wiki_embeddings_hnsw_cosine
    ON agent.wiki_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- DB-006: 개인 Wiki 전체 재구성 시점과 변경 요약을 버전으로 저장한다.
CREATE TABLE agent.wiki_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL,
    version bigint NOT NULL CHECK (version > 0),
    status text NOT NULL DEFAULT 'building'
        CHECK (status IN ('building', 'active', 'failed', 'retired')),
    document_count integer NOT NULL DEFAULT 0 CHECK (document_count >= 0),
    chunk_count integer NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
    change_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    built_by_job_id uuid REFERENCES agent.agent_jobs(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    activated_at timestamptz,
    UNIQUE (user_id, version)
);

CREATE UNIQUE INDEX uq_wiki_versions_active
    ON agent.wiki_versions (user_id)
    WHERE status = 'active';

-- DB-007: 사용자 관심사 Profile, Topic과 근거를 버전별 저장한다.
CREATE TABLE agent.user_interest_profiles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL,
    version bigint NOT NULL CHECK (version > 0),
    wiki_version_id uuid REFERENCES agent.wiki_versions(id),
    status text NOT NULL DEFAULT 'building'
        CHECK (status IN ('building', 'active', 'failed', 'retired')),
    calculated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (user_id, version)
);

CREATE UNIQUE INDEX uq_user_interest_profiles_active
    ON agent.user_interest_profiles (user_id)
    WHERE status = 'active';

CREATE TABLE agent.user_interests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id uuid NOT NULL REFERENCES agent.user_interest_profiles(id) ON DELETE CASCADE,
    user_id text NOT NULL,
    parent_interest_id uuid REFERENCES agent.user_interests(id),
    topic text NOT NULL,
    category text,
    score numeric(8, 6) NOT NULL CHECK (score BETWEEN -1 AND 1),
    confidence numeric(8, 6) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    is_blocked boolean NOT NULL DEFAULT false,
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (profile_id, topic)
);

CREATE INDEX ix_user_interests_rank
    ON agent.user_interests (user_id, score DESC)
    WHERE NOT is_blocked;

CREATE TABLE agent.interest_evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    interest_id uuid NOT NULL REFERENCES agent.user_interests(id) ON DELETE CASCADE,
    user_id text NOT NULL,
    document_id uuid REFERENCES agent.wiki_documents(id),
    source_event_id uuid REFERENCES agent.wiki_source_events(id),
    weight numeric(8, 6) NOT NULL DEFAULT 1,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (document_id IS NOT NULL OR source_event_id IS NOT NULL)
);

-- DB-008: 외부 Source 설정을 보관하고 Secret 원문 대신 참조만 저장한다.
CREATE TABLE agent.global_sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_key text NOT NULL UNIQUE,
    connector_type text NOT NULL,
    display_name text NOT NULL,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'paused', 'deleted')),
    schedule_cron text,
    keywords text[] NOT NULL DEFAULT '{}',
    languages text[] NOT NULL DEFAULT '{}',
    categories text[] NOT NULL DEFAULT '{}',
    secret_ref text,
    quota_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
    connector_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    trust_score numeric(5, 4) CHECK (trust_score IS NULL OR trust_score BETWEEN 0 AND 1),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- DB-009: Source별 수집 실행 결과와 재시작 Cursor를 저장한다.
CREATE TABLE agent.global_collection_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id uuid NOT NULL REFERENCES agent.global_sources(id),
    job_id uuid REFERENCES agent.agent_jobs(id),
    status text NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'partial', 'failed')),
    cursor_before jsonb,
    cursor_after jsonb,
    fetched_count integer NOT NULL DEFAULT 0 CHECK (fetched_count >= 0),
    created_count integer NOT NULL DEFAULT 0 CHECK (created_count >= 0),
    duplicate_count integer NOT NULL DEFAULT 0 CHECK (duplicate_count >= 0),
    failed_count integer NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
    error_code text,
    error_message text,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz
);

CREATE INDEX ix_global_collection_runs_source
    ON agent.global_collection_runs (source_id, started_at DESC);

-- DB-013: 탐지한 Global Trend와 근거 문서 묶음을 저장한다.
CREATE TABLE agent.global_trends (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    topic text NOT NULL,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'expired', 'rejected')),
    freshness_score numeric(8, 6) CHECK (freshness_score BETWEEN 0 AND 1),
    importance_score numeric(8, 6) CHECK (importance_score BETWEEN 0 AND 1),
    source_diversity_score numeric(8, 6) CHECK (source_diversity_score BETWEEN 0 AND 1),
    window_started_at timestamptz NOT NULL,
    window_ended_at timestamptz NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (window_ended_at > window_started_at)
);

CREATE TABLE agent.global_trend_documents (
    trend_id uuid NOT NULL REFERENCES agent.global_trends(id) ON DELETE CASCADE,
    document_id uuid NOT NULL REFERENCES agent.wiki_documents(id) ON DELETE CASCADE,
    relevance_score numeric(8, 6) NOT NULL CHECK (relevance_score BETWEEN 0 AND 1),
    PRIMARY KEY (trend_id, document_id)
);

-- DB-014: 생성 또는 추천 파이프라인으로 넘길 Discovery 후보를 저장한다.
CREATE TABLE agent.discovery_candidates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_type text NOT NULL CHECK (candidate_type IN ('generation', 'recommendation')),
    trend_id uuid REFERENCES agent.global_trends(id),
    document_id uuid REFERENCES agent.wiki_documents(id),
    user_id text,
    score numeric(8, 6) NOT NULL CHECK (score BETWEEN 0 AND 1),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'selected', 'rejected', 'expired')),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (trend_id IS NOT NULL OR document_id IS NOT NULL)
);

CREATE INDEX ix_discovery_candidates_pending
    ON agent.discovery_candidates (candidate_type, score DESC, created_at)
    WHERE status = 'pending';

-- DB-015: 콘텐츠 생성 요청을 Job과 사용자 컨텍스트 버전에 연결한다.
CREATE TABLE agent.generation_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id uuid NOT NULL UNIQUE REFERENCES agent.agent_jobs(id),
    user_id text NOT NULL,
    user_context_snapshot_id uuid NOT NULL REFERENCES agent.user_context_snapshots(id),
    topic text NOT NULL,
    content_type text NOT NULL,
    plan text NOT NULL CHECK (plan IN ('free', 'paid')),
    language text NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE agent.generation_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    generation_request_id uuid NOT NULL REFERENCES agent.generation_requests(id) ON DELETE CASCADE,
    user_id text NOT NULL,
    attempt_number integer NOT NULL CHECK (attempt_number > 0),
    prompt_version_id uuid REFERENCES agent.prompt_versions(id),
    model_config_id uuid REFERENCES agent.model_configs(id),
    retrieval_config_id uuid REFERENCES agent.retrieval_configs(id),
    status text NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed', 'rejected')),
    input_tokens integer CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens integer CHECK (output_tokens IS NULL OR output_tokens >= 0),
    estimated_cost numeric(14, 6) CHECK (estimated_cost IS NULL OR estimated_cost >= 0),
    latency_ms integer CHECK (latency_ms IS NULL OR latency_ms >= 0),
    error_code text,
    error_message text,
    run_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    UNIQUE (generation_request_id, attempt_number)
);

-- DB-016: service-db에 발행하기 전 생성 콘텐츠 후보와 버전을 저장한다.
CREATE TABLE agent.generated_content_candidates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    generation_request_id uuid NOT NULL REFERENCES agent.generation_requests(id),
    generation_run_id uuid NOT NULL REFERENCES agent.generation_runs(id),
    user_id text NOT NULL,
    content_id text NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    content_type text NOT NULL,
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'ready', 'published', 'failed', 'archived', 'superseded', 'rejected')),
    title text NOT NULL,
    summary text NOT NULL,
    body text NOT NULL,
    structured_body jsonb NOT NULL DEFAULT '{}'::jsonb,
    snapshot_hash text NOT NULL CHECK (length(snapshot_hash) > 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (content_id, version)
);

CREATE INDEX ix_generated_content_user
    ON agent.generated_content_candidates (user_id, created_at DESC);

-- DB-017: 생성 콘텐츠 주장과 문서·Chunk 출처를 순서대로 연결한다.
CREATE TABLE agent.citations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id uuid NOT NULL REFERENCES agent.generated_content_candidates(id) ON DELETE CASCADE,
    user_id text NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    document_version_id uuid REFERENCES agent.wiki_document_versions(id),
    chunk_id uuid REFERENCES agent.wiki_chunks(id),
    title text NOT NULL,
    url text,
    quoted_text text,
    claim_paths text[] NOT NULL DEFAULT '{}',
    citation_hash text CHECK (citation_hash IS NULL OR length(citation_hash) = 64),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (candidate_id, ordinal),
    CHECK (document_version_id IS NOT NULL OR url IS NOT NULL)
);

-- DB-018: 이미지 등 Object Storage Asset의 메타데이터와 GCS URI만 저장한다.
CREATE TABLE agent.content_assets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id uuid NOT NULL REFERENCES agent.generated_content_candidates(id) ON DELETE CASCADE,
    user_id text NOT NULL,
    asset_type text NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'ready', 'failed', 'deleted')),
    storage_uri text NOT NULL,
    content_type text,
    byte_size bigint CHECK (byte_size IS NULL OR byte_size >= 0),
    checksum text CHECK (checksum IS NULL OR length(checksum) = 64),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- DB-019, DB-020: 품질과 안전성 평가 결과를 독립적으로 축적한다.
CREATE TABLE agent.quality_evaluations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id uuid NOT NULL REFERENCES agent.generated_content_candidates(id) ON DELETE CASCADE,
    user_id text NOT NULL,
    evaluator text NOT NULL,
    score numeric(8, 6) CHECK (score IS NULL OR score BETWEEN 0 AND 1),
    passed boolean NOT NULL,
    metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
    reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE agent.safety_evaluations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id uuid NOT NULL REFERENCES agent.generated_content_candidates(id) ON DELETE CASCADE,
    user_id text NOT NULL,
    evaluator text NOT NULL,
    passed boolean NOT NULL,
    categories jsonb NOT NULL DEFAULT '{}'::jsonb,
    reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- DB-021: 후속 추천 Agent가 사용할 사용자별 후보와 점수를 저장한다.
CREATE TABLE agent.recommendation_candidates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL,
    content_id text NOT NULL,
    score numeric(8, 6) NOT NULL,
    reason jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'selected', 'rejected', 'expired')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    expires_at timestamptz,
    UNIQUE (user_id, content_id)
);

-- 발행 Snapshot은 Service Worker 계약의 Version과 Hash를 그대로 보존한다.
CREATE TABLE agent.publish_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id uuid NOT NULL REFERENCES agent.generated_content_candidates(id),
    user_id text NOT NULL,
    content_id text NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    snapshot_hash text NOT NULL CHECK (length(snapshot_hash) > 0),
    payload jsonb NOT NULL,
    status text NOT NULL DEFAULT 'ready'
        CHECK (status IN ('ready', 'published', 'failed', 'superseded')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    acknowledged_at timestamptz,
    failure_reason text,
    UNIQUE (content_id, version)
);

CREATE TABLE agent.publish_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id uuid NOT NULL REFERENCES agent.publish_snapshots(id) ON DELETE CASCADE,
    user_id text NOT NULL,
    attempt_number integer NOT NULL CHECK (attempt_number > 0),
    worker_event_id text,
    status text NOT NULL CHECK (status IN ('requested', 'published', 'failed')),
    failure_reason text,
    requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    acknowledged_at timestamptz,
    UNIQUE (snapshot_id, attempt_number)
);

-- DB-027: Agent DB 변경과 Integration Event 발행을 한 트랜잭션으로 묶는다.
CREATE TABLE agent.event_outbox (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_type text NOT NULL,
    aggregate_id text NOT NULL,
    event_type text NOT NULL,
    schema_version integer NOT NULL DEFAULT 1 CHECK (schema_version > 0),
    deduplication_key text NOT NULL UNIQUE,
    payload jsonb NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'publishing', 'published', 'failed', 'dead_letter')),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    published_at timestamptz,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX ix_event_outbox_pending
    ON agent.event_outbox (available_at, created_at)
    WHERE status IN ('pending', 'failed');

CREATE TABLE agent.event_inbox (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    consumer_name text NOT NULL,
    event_id text NOT NULL,
    event_type text NOT NULL,
    schema_version integer NOT NULL CHECK (schema_version > 0),
    payload_hash text NOT NULL CHECK (length(payload_hash) = 64),
    status text NOT NULL DEFAULT 'received'
        CHECK (status IN ('received', 'processed', 'failed', 'ignored')),
    received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    processed_at timestamptz,
    error_message text,
    UNIQUE (consumer_name, event_id)
);

-- DB-028: External API Key 원문은 저장하지 않고 Hash와 식별 Prefix만 저장한다.
CREATE TABLE agent.api_keys (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key_prefix text NOT NULL UNIQUE,
    key_hash text NOT NULL UNIQUE,
    principal_id text NOT NULL,
    scopes text[] NOT NULL DEFAULT '{}',
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'revoked', 'expired')),
    expires_at timestamptz,
    last_used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    revoked_at timestamptz
);

-- DB-029: 모든 Provider 호출의 Token, 비용, 지연과 Trace를 기록한다.
CREATE TABLE agent.usage_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id uuid REFERENCES agent.agent_jobs(id),
    generation_run_id uuid REFERENCES agent.generation_runs(id),
    user_id text,
    feature_id text NOT NULL,
    provider text NOT NULL,
    model_name text,
    operation text NOT NULL,
    input_tokens integer NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens integer NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    request_count integer NOT NULL DEFAULT 1 CHECK (request_count > 0),
    estimated_cost numeric(14, 6) NOT NULL DEFAULT 0 CHECK (estimated_cost >= 0),
    latency_ms integer CHECK (latency_ms IS NULL OR latency_ms >= 0),
    status text NOT NULL CHECK (status IN ('succeeded', 'failed', 'cached')),
    request_id text,
    trace_id text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX ix_usage_logs_created
    ON agent.usage_logs (created_at DESC);
CREATE INDEX ix_usage_logs_user_created
    ON agent.usage_logs (user_id, created_at DESC)
    WHERE user_id IS NOT NULL;

-- DB-030: 관리자 변경과 민감 데이터 접근을 append-only Audit로 남긴다.
CREATE TABLE agent.audit_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_type text NOT NULL,
    actor_id text NOT NULL,
    action text NOT NULL,
    resource_type text NOT NULL,
    resource_id text,
    target_user_id text,
    request_id text,
    trace_id text,
    source_ip inet,
    succeeded boolean NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX ix_audit_logs_resource
    ON agent.audit_logs (resource_type, resource_id, created_at DESC);
CREATE INDEX ix_audit_logs_target_user
    ON agent.audit_logs (target_user_id, created_at DESC)
    WHERE target_user_id IS NOT NULL;

-- 사용자별 RLS는 Application Runtime이 테이블 소유자가 아닐 때 방어 계층으로 동작한다.
ALTER TABLE agent.user_context_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.agent_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.agent_job_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.wiki_source_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.wiki_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.wiki_document_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.wiki_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.wiki_embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.wiki_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.user_interest_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.user_interests ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.interest_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.generation_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.generation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.generated_content_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.citations ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.content_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.quality_evaluations ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.safety_evaluations ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.recommendation_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.publish_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.publish_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent.usage_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_context_isolation ON agent.user_context_snapshots
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());
CREATE POLICY job_isolation ON agent.agent_jobs
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());
CREATE POLICY job_attempt_isolation ON agent.agent_job_attempts
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());
CREATE POLICY wiki_source_event_isolation ON agent.wiki_source_events
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());
CREATE POLICY wiki_document_read ON agent.wiki_documents
    FOR SELECT
    USING (knowledge_scope = 'global' OR agent.has_system_scope() OR user_id = agent.current_user_id());
CREATE POLICY wiki_document_write ON agent.wiki_documents
    FOR ALL
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());

CREATE POLICY wiki_version_row_read ON agent.wiki_document_versions
    FOR SELECT
    USING (namespace_key = 'global' OR agent.has_system_scope() OR namespace_key = 'user/' || agent.current_user_id());
CREATE POLICY wiki_version_row_write ON agent.wiki_document_versions
    FOR ALL
    USING (agent.has_system_scope() OR namespace_key = 'user/' || agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR namespace_key = 'user/' || agent.current_user_id());
CREATE POLICY wiki_chunk_read ON agent.wiki_chunks
    FOR SELECT
    USING (namespace_key = 'global' OR agent.has_system_scope() OR namespace_key = 'user/' || agent.current_user_id());
CREATE POLICY wiki_chunk_write ON agent.wiki_chunks
    FOR ALL
    USING (agent.has_system_scope() OR namespace_key = 'user/' || agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR namespace_key = 'user/' || agent.current_user_id());
CREATE POLICY wiki_embedding_read ON agent.wiki_embeddings
    FOR SELECT
    USING (namespace_key = 'global' OR agent.has_system_scope() OR namespace_key = 'user/' || agent.current_user_id());
CREATE POLICY wiki_embedding_write ON agent.wiki_embeddings
    FOR ALL
    USING (agent.has_system_scope() OR namespace_key = 'user/' || agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR namespace_key = 'user/' || agent.current_user_id());

CREATE POLICY wiki_build_version_isolation ON agent.wiki_versions
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());
CREATE POLICY interest_profile_isolation ON agent.user_interest_profiles
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());
CREATE POLICY interest_isolation ON agent.user_interests
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());
CREATE POLICY interest_evidence_isolation ON agent.interest_evidence
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());

CREATE POLICY generation_request_isolation ON agent.generation_requests
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());
CREATE POLICY generation_run_isolation ON agent.generation_runs
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());
CREATE POLICY generated_candidate_isolation ON agent.generated_content_candidates
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());
CREATE POLICY citation_isolation ON agent.citations
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());
CREATE POLICY content_asset_isolation ON agent.content_assets
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());
CREATE POLICY quality_evaluation_isolation ON agent.quality_evaluations
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());
CREATE POLICY safety_evaluation_isolation ON agent.safety_evaluations
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());
CREATE POLICY recommendation_isolation ON agent.recommendation_candidates
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());
CREATE POLICY publish_snapshot_isolation ON agent.publish_snapshots
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());
CREATE POLICY publish_attempt_isolation ON agent.publish_attempts
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());
CREATE POLICY usage_log_isolation ON agent.usage_logs
    USING (agent.has_system_scope() OR user_id = agent.current_user_id())
    WITH CHECK (agent.has_system_scope() OR user_id = agent.current_user_id());

CREATE TRIGGER set_prompt_templates_updated_at
    BEFORE UPDATE ON agent.prompt_templates
    FOR EACH ROW EXECUTE FUNCTION agent.set_updated_at();
CREATE TRIGGER set_agent_jobs_updated_at
    BEFORE UPDATE ON agent.agent_jobs
    FOR EACH ROW EXECUTE FUNCTION agent.set_updated_at();
CREATE TRIGGER set_wiki_source_events_updated_at
    BEFORE UPDATE ON agent.wiki_source_events
    FOR EACH ROW EXECUTE FUNCTION agent.set_updated_at();
CREATE TRIGGER set_wiki_documents_updated_at
    BEFORE UPDATE ON agent.wiki_documents
    FOR EACH ROW EXECUTE FUNCTION agent.set_updated_at();
CREATE TRIGGER set_global_sources_updated_at
    BEFORE UPDATE ON agent.global_sources
    FOR EACH ROW EXECUTE FUNCTION agent.set_updated_at();
CREATE TRIGGER set_generation_requests_updated_at
    BEFORE UPDATE ON agent.generation_requests
    FOR EACH ROW EXECUTE FUNCTION agent.set_updated_at();
CREATE TRIGGER set_generated_candidates_updated_at
    BEFORE UPDATE ON agent.generated_content_candidates
    FOR EACH ROW EXECUTE FUNCTION agent.set_updated_at();

CREATE TABLE agent.schema_migrations (
    version integer PRIMARY KEY,
    description text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

INSERT INTO agent.schema_migrations (version, description)
VALUES (1, 'Initial Agent DB schema');

COMMIT;
