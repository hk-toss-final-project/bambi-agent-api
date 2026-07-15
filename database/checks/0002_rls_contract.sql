-- Table Owner가 아닌 Runtime Role에서 사용자별 RLS 격리가 동작하는지 검증한다.

\set ON_ERROR_STOP on

BEGIN;

CREATE ROLE agent_rls_contract_role NOLOGIN;
GRANT USAGE ON SCHEMA agent TO agent_rls_contract_role;
GRANT SELECT ON agent.user_context_snapshots TO agent_rls_contract_role;
GRANT SELECT, DELETE ON agent.wiki_documents TO agent_rls_contract_role;
GRANT SELECT, DELETE ON agent.user_source_documents TO agent_rls_contract_role;
GRANT SELECT, DELETE ON agent.wiki_document_relations TO agent_rls_contract_role;
GRANT SELECT, DELETE ON agent.wiki_version_documents TO agent_rls_contract_role;

INSERT INTO agent.user_context_snapshots (
    user_id,
    context_version,
    plan,
    preferred_language
)
VALUES
    ('rls-user-a', 1, 'free', 'ko'),
    ('rls-user-b', 1, 'paid', 'ko');

INSERT INTO agent.wiki_documents (
    knowledge_scope,
    namespace_key,
    user_id,
    source_type,
    canonical_url,
    content_hash,
    document_kind,
    document_key,
    file_path,
    domain
)
VALUES
    (
        'global', 'global', NULL, 'news_api',
        'https://rls-contract.invalid/global', repeat('a', 64),
        'document', 'global-source', 'documents/global-source.md', NULL
    ),
    (
        'personal', 'user/rls-user-a', 'rls-user-a', 'llm_wiki',
        'https://rls-contract.invalid/user-a', repeat('b', 64),
        'entity', 'orders', 'entities/orders.md', 'commerce'
    ),
    (
        'personal', 'user/rls-user-b', 'rls-user-b', 'llm_wiki',
        'https://rls-contract.invalid/user-b', repeat('c', 64),
        'entity', 'orders', 'entities/orders.md', 'commerce'
    ),
    (
        'personal', 'user/rls-user-a', 'rls-user-a', 'llm_wiki',
        NULL, repeat('f', 64),
        'concept', 'soft-delete', 'concepts/soft-delete.md', NULL
    ),
    (
        'personal', 'user/rls-user-b', 'rls-user-b', 'llm_wiki',
        NULL, repeat('g', 64),
        'concept', 'soft-delete', 'concepts/soft-delete.md', NULL
    );

INSERT INTO agent.wiki_document_versions (
    document_id,
    namespace_key,
    version,
    title,
    normalized_content,
    content_hash
)
SELECT
    document.id,
    document.namespace_key,
    1,
    document.document_key,
    '# ' || document.document_key,
    CASE document.user_id
        WHEN 'rls-user-a' THEN repeat('h', 64)
        ELSE repeat('i', 64)
    END
FROM agent.wiki_documents AS document
WHERE document.document_kind = 'entity'
  AND document.user_id IN ('rls-user-a', 'rls-user-b');

INSERT INTO agent.wiki_versions (
    user_id,
    namespace_key,
    version,
    status,
    document_count
)
VALUES
    ('rls-user-a', 'user/rls-user-a', 1, 'active', 1),
    ('rls-user-b', 'user/rls-user-b', 1, 'active', 1);

INSERT INTO agent.wiki_document_relations (
    source_document_id,
    target_document_id,
    namespace_key,
    relation_type
)
SELECT
    entity.id,
    concept.id,
    entity.namespace_key,
    'applies_concept'
FROM agent.wiki_documents AS entity
JOIN agent.wiki_documents AS concept
  ON concept.namespace_key = entity.namespace_key
 AND concept.document_kind = 'concept'
 AND concept.document_key = 'soft-delete'
WHERE entity.document_kind = 'entity'
  AND entity.document_key = 'orders';

INSERT INTO agent.wiki_version_documents (
    wiki_version_id,
    document_version_id,
    namespace_key,
    file_path
)
SELECT
    wiki_version.id,
    document_version.id,
    wiki_version.namespace_key,
    document.file_path
FROM agent.wiki_versions AS wiki_version
JOIN agent.wiki_documents AS document
  ON document.namespace_key = wiki_version.namespace_key
 AND document.document_kind = 'entity'
 AND document.document_key = 'orders'
JOIN agent.wiki_document_versions AS document_version
  ON document_version.document_id = document.id
 AND document_version.namespace_key = document.namespace_key;

INSERT INTO agent.user_source_documents (
    user_id,
    namespace_key,
    source_type,
    canonical_url,
    content_hash
)
VALUES
    ('rls-user-a', 'user/rls-user-a', 'url', 'https://rls-contract.invalid/source-a', repeat('d', 64)),
    ('rls-user-b', 'user/rls-user-b', 'url', 'https://rls-contract.invalid/source-b', repeat('e', 64));

SET ROLE agent_rls_contract_role;
SET LOCAL app.user_id = 'rls-user-a';
SET LOCAL app.access_scope = 'user';

DO $$
DECLARE
    visible_rows integer;
BEGIN
    SELECT count(*) INTO visible_rows
    FROM agent.user_context_snapshots
    WHERE user_id IN ('rls-user-a', 'rls-user-b');

    IF visible_rows <> 1 THEN
        RAISE EXCEPTION 'user scope expected 1 row but saw %', visible_rows;
    END IF;
END;
$$;

DO $$
DECLARE
    visible_relations integer;
    visible_version_documents integer;
    deleted_rows integer;
BEGIN
    SELECT count(*) INTO visible_relations
    FROM agent.wiki_document_relations
    WHERE relation_type = 'applies_concept';

    IF visible_relations <> 1 THEN
        RAISE EXCEPTION 'user scope expected 1 Wiki relation but saw %', visible_relations;
    END IF;

    SELECT count(*) INTO visible_version_documents
    FROM agent.wiki_version_documents;

    IF visible_version_documents <> 1 THEN
        RAISE EXCEPTION 'user scope expected 1 Wiki version document but saw %', visible_version_documents;
    END IF;

    DELETE FROM agent.wiki_document_relations
    WHERE namespace_key = 'user/rls-user-b';
    GET DIAGNOSTICS deleted_rows = ROW_COUNT;

    IF deleted_rows <> 0 THEN
        RAISE EXCEPTION 'user scope deleted % other-user Wiki relations', deleted_rows;
    END IF;

    DELETE FROM agent.wiki_version_documents
    WHERE namespace_key = 'user/rls-user-b';
    GET DIAGNOSTICS deleted_rows = ROW_COUNT;

    IF deleted_rows <> 0 THEN
        RAISE EXCEPTION 'user scope deleted % other-user Wiki version documents', deleted_rows;
    END IF;
END;
$$;

DO $$
DECLARE
    visible_rows integer;
    deleted_rows integer;
BEGIN
    SELECT count(*) INTO visible_rows
    FROM agent.user_source_documents
    WHERE canonical_url LIKE 'https://rls-contract.invalid/source-%';

    IF visible_rows <> 1 THEN
        RAISE EXCEPTION 'user scope expected 1 source row but saw %', visible_rows;
    END IF;

    DELETE FROM agent.user_source_documents
    WHERE canonical_url = 'https://rls-contract.invalid/source-b';
    GET DIAGNOSTICS deleted_rows = ROW_COUNT;

    IF deleted_rows <> 0 THEN
        RAISE EXCEPTION 'user scope deleted % other-user source rows', deleted_rows;
    END IF;
END;
$$;

DO $$
DECLARE
    visible_rows integer;
    deleted_rows integer;
BEGIN
    SELECT count(*) INTO visible_rows
    FROM agent.wiki_documents
    WHERE canonical_url LIKE 'https://rls-contract.invalid/%';

    IF visible_rows <> 2 THEN
        RAISE EXCEPTION 'user scope expected global and own Wiki rows but saw %', visible_rows;
    END IF;

    DELETE FROM agent.wiki_documents
    WHERE knowledge_scope = 'global'
      AND canonical_url = 'https://rls-contract.invalid/global';
    GET DIAGNOSTICS deleted_rows = ROW_COUNT;

    IF deleted_rows <> 0 THEN
        RAISE EXCEPTION 'user scope deleted % global Wiki rows', deleted_rows;
    END IF;
END;
$$;

SET LOCAL app.access_scope = 'system';

DO $$
DECLARE
    visible_rows integer;
BEGIN
    SELECT count(*) INTO visible_rows
    FROM agent.user_context_snapshots
    WHERE user_id IN ('rls-user-a', 'rls-user-b');

    IF visible_rows <> 2 THEN
        RAISE EXCEPTION 'system scope expected 2 rows but saw %', visible_rows;
    END IF;

    SELECT count(*) INTO visible_rows
    FROM agent.user_source_documents
    WHERE canonical_url LIKE 'https://rls-contract.invalid/source-%';

    IF visible_rows <> 2 THEN
        RAISE EXCEPTION 'system scope expected 2 source rows but saw %', visible_rows;
    END IF;

    SELECT count(*) INTO visible_rows
    FROM agent.wiki_document_relations
    WHERE relation_type = 'applies_concept';

    IF visible_rows <> 2 THEN
        RAISE EXCEPTION 'system scope expected 2 Wiki relations but saw %', visible_rows;
    END IF;

    SELECT count(*) INTO visible_rows
    FROM agent.wiki_version_documents;

    IF visible_rows <> 2 THEN
        RAISE EXCEPTION 'system scope expected 2 Wiki version documents but saw %', visible_rows;
    END IF;
END;
$$;

RESET ROLE;
ROLLBACK;

SELECT 'agent-db RLS contract passed' AS result;
