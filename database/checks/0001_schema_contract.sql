-- Agent DB 초기 스키마의 필수 Extension, Table, Index와 RLS 계약을 검증한다.

\set ON_ERROR_STOP on

DO $$
DECLARE
    required_tables text[] := ARRAY[
        'user_context_snapshots',
        'wiki_source_events',
        'wiki_documents',
        'wiki_document_versions',
        'wiki_chunks',
        'wiki_embeddings',
        'wiki_versions',
        'user_interest_profiles',
        'user_interests',
        'global_sources',
        'global_collection_runs',
        'global_trends',
        'discovery_candidates',
        'generation_requests',
        'generated_content_candidates',
        'citations',
        'content_assets',
        'quality_evaluations',
        'safety_evaluations',
        'recommendation_candidates',
        'prompt_templates',
        'model_configs',
        'retrieval_configs',
        'embedding_configs',
        'agent_jobs',
        'event_outbox',
        'api_keys',
        'usage_logs',
        'audit_logs',
        'publish_snapshots'
    ];
    table_name text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        RAISE EXCEPTION 'vector extension is missing';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
        RAISE EXCEPTION 'pg_trgm extension is missing';
    END IF;

    FOREACH table_name IN ARRAY required_tables LOOP
        IF to_regclass('agent.' || table_name) IS NULL THEN
            RAISE EXCEPTION 'required table agent.% is missing', table_name;
        END IF;
    END LOOP;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'agent'
          AND indexname = 'ix_wiki_embeddings_hnsw_cosine'
          AND indexdef LIKE '%USING hnsw%'
    ) THEN
        RAISE EXCEPTION 'HNSW embedding index is missing';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'agent'
          AND relation.relname IN (
              'user_context_snapshots',
              'wiki_documents',
              'wiki_chunks',
              'wiki_embeddings',
              'generated_content_candidates'
          )
          AND NOT relation.relrowsecurity
    ) THEN
        RAISE EXCEPTION 'required personal-data RLS is disabled';
    END IF;
END;
$$;

SELECT 'agent-db schema contract passed' AS result;
