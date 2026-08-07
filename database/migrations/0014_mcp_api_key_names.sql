-- MCP Personal Access Token을 사용자가 식별할 수 있도록 이름과 조회 인덱스를 추가한다.
--
-- 각 항목을 IF NOT EXISTS로 감싼 이유: 이 Migration은 처음 배포될 때
-- BEGIN/COMMIT과 schema_migrations 기록이 빠져 있었다. 그래서 Runner가 ALTER를
-- Autocommit으로 적용한 뒤 "version 14를 기록하지 않았다"며 실패했고, 그 DB에는
-- 컬럼·인덱스만 남고 버전은 기록되지 않은 상태가 됐다. 그 상태에서 다시 돌려도
-- 통과해야 복구가 된다.

\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE agent.api_keys
    ADD COLUMN IF NOT EXISTS name text NOT NULL DEFAULT 'MCP 연결';

ALTER TABLE agent.api_keys
    ALTER COLUMN name DROP DEFAULT;

ALTER TABLE agent.api_keys
    DROP CONSTRAINT IF EXISTS ck_api_keys_name_length;
ALTER TABLE agent.api_keys
    ADD CONSTRAINT ck_api_keys_name_length
        CHECK (char_length(name) BETWEEN 1 AND 64);

CREATE INDEX IF NOT EXISTS ix_api_keys_principal_created
    ON agent.api_keys (principal_id, created_at DESC);

INSERT INTO agent.schema_migrations (version, description)
VALUES (14, 'Name MCP personal access tokens and index them per principal');

COMMIT;
