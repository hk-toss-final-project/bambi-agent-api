-- Agent DB 초기 스키마의 필수 Extension, Table, Index와 RLS 계약을 검증한다.

\set ON_ERROR_STOP on

DO $$
DECLARE
    required_tables text[] := ARRAY[
        'user_context_snapshots',
        'wiki_source_events',
        'user_source_documents',
        'user_source_document_versions',
        'wiki_documents',
        'wiki_document_versions',
        'wiki_document_sources',
        'wiki_document_relations',
        'wiki_chunks',
        'wiki_embeddings',
        'wiki_versions',
        'wiki_version_documents',
        'user_interest_profiles',
        'user_interests',
        'global_sources',
        'global_collection_runs',
        'global_source_documents',
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
    required_web_clipping_columns text[] := ARRAY[
        'author',
        'published_at',
        'clipped_on',
        'description',
        'tags',
        'content_format'
    ];
    required_wiki_document_columns text[] := ARRAY[
        'document_kind',
        'document_key',
        'file_path',
        'domain'
    ];
    required_table_name text;
    required_column_name text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        RAISE EXCEPTION 'vector extension is missing';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
        RAISE EXCEPTION 'pg_trgm extension is missing';
    END IF;

    FOREACH required_table_name IN ARRAY required_tables LOOP
        IF to_regclass('agent.' || required_table_name) IS NULL THEN
            RAISE EXCEPTION 'required table agent.% is missing', required_table_name;
        END IF;
    END LOOP;

    FOREACH required_column_name IN ARRAY required_web_clipping_columns LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.columns AS schema_column
            WHERE schema_column.table_schema = 'agent'
              AND schema_column.table_name = 'user_source_document_versions'
              AND schema_column.column_name = required_column_name
        ) THEN
            RAISE EXCEPTION 'required web clipping column agent.user_source_document_versions.% is missing', required_column_name;
        END IF;
    END LOOP;

    FOREACH required_column_name IN ARRAY required_wiki_document_columns LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.columns AS schema_column
            WHERE schema_column.table_schema = 'agent'
              AND schema_column.table_name = 'wiki_documents'
              AND schema_column.column_name = required_column_name
        ) THEN
            RAISE EXCEPTION 'required structured Wiki column agent.wiki_documents.% is missing', required_column_name;
        END IF;
    END LOOP;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns AS schema_column
        WHERE schema_column.table_schema = 'agent'
          AND schema_column.table_name = 'wiki_versions'
          AND schema_column.column_name = 'namespace_key'
    ) THEN
        RAISE EXCEPTION 'required structured Wiki column agent.wiki_versions.namespace_key is missing';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.columns AS schema_column
        WHERE schema_column.table_schema = 'agent'
          AND schema_column.table_name = 'wiki_document_versions'
          AND schema_column.column_name = ANY(required_web_clipping_columns)
    ) THEN
        RAISE EXCEPTION 'raw web clipping columns remain in agent.wiki_document_versions';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'agent'
          AND indexname = 'ix_wiki_embeddings_hnsw_cosine'
          AND indexdef LIKE '%USING hnsw%'
    ) THEN
        RAISE EXCEPTION 'HNSW embedding index is missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'agent'
          AND indexname = 'uq_wiki_documents_schema_per_namespace'
          AND indexdef LIKE '%UNIQUE%'
    ) THEN
        RAISE EXCEPTION 'single schema document index is missing';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'agent'
          AND relation.relname IN (
              'user_context_snapshots',
              'user_source_documents',
              'user_source_document_versions',
              'wiki_documents',
              'wiki_document_sources',
              'wiki_document_relations',
              'wiki_version_documents',
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
