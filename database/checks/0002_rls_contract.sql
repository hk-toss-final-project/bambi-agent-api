-- Table Owner가 아닌 Runtime Role에서 사용자별 RLS 격리가 동작하는지 검증한다.

\set ON_ERROR_STOP on

BEGIN;

CREATE ROLE agent_rls_contract_role NOLOGIN;
GRANT USAGE ON SCHEMA agent TO agent_rls_contract_role;
GRANT SELECT ON agent.user_context_snapshots TO agent_rls_contract_role;
GRANT SELECT, DELETE ON agent.wiki_documents TO agent_rls_contract_role;

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
    content_hash
)
VALUES
    ('global', 'global', NULL, 'news_api', repeat('a', 64)),
    ('personal', 'user/rls-user-a', 'rls-user-a', 'url', repeat('b', 64)),
    ('personal', 'user/rls-user-b', 'rls-user-b', 'url', repeat('c', 64));

SET ROLE agent_rls_contract_role;
SET LOCAL app.user_id = 'rls-user-a';
SET LOCAL app.access_scope = 'user';

DO $$
DECLARE
    visible_rows integer;
BEGIN
    SELECT count(*) INTO visible_rows
    FROM agent.user_context_snapshots;

    IF visible_rows <> 1 THEN
        RAISE EXCEPTION 'user scope expected 1 row but saw %', visible_rows;
    END IF;
END;
$$;

DO $$
DECLARE
    visible_rows integer;
    deleted_rows integer;
BEGIN
    SELECT count(*) INTO visible_rows
    FROM agent.wiki_documents;

    IF visible_rows <> 2 THEN
        RAISE EXCEPTION 'user scope expected global and own Wiki rows but saw %', visible_rows;
    END IF;

    DELETE FROM agent.wiki_documents
    WHERE knowledge_scope = 'global';
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
    FROM agent.user_context_snapshots;

    IF visible_rows <> 2 THEN
        RAISE EXCEPTION 'system scope expected 2 rows but saw %', visible_rows;
    END IF;
END;
$$;

RESET ROLE;
ROLLBACK;

SELECT 'agent-db RLS contract passed' AS result;
