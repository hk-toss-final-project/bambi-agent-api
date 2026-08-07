-- MCP Personal Access Token을 사용자가 식별할 수 있도록 이름과 조회 인덱스를 추가한다.
--
-- 2026-08-07 수정: 원본에 `INSERT INTO agent.schema_migrations` 가 빠져 있어
-- 러너의 기록 검증(`Migration ... did not record schema_migrations version 14`)에
-- 걸려 실패했다. DDL 은 그 시점에 이미 커밋된 뒤라 다음 실행부터는
-- `column "name" of relation "api_keys" already exists` 로 계속 실패했다 —
-- 운영 배포가 08-06 17:22 부터 8회 연속 빨간불이었다(운영은 ledger 에 version 14 를
-- 수동 INSERT 해서 해소했고, 이 파일이 고쳐지면 그 수동 조치와 결과가 같아진다).
--
-- 재실행 안전성을 위해 모든 DDL 에 존재 검사를 붙이고 트랜잭션으로 묶는다.
-- 스키마 결과물은 원본과 동일하다.

\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE agent.api_keys
    ADD COLUMN IF NOT EXISTS name text NOT NULL DEFAULT 'MCP 연결';

-- 기존 행을 채운 뒤 기본값을 걷어낸다. 기본값이 이미 없어도 오류가 아니다.
ALTER TABLE agent.api_keys
    ALTER COLUMN name DROP DEFAULT;

-- ADD CONSTRAINT 에는 IF NOT EXISTS 가 없어 DROP 선행으로 멱등화한다.
ALTER TABLE agent.api_keys
    DROP CONSTRAINT IF EXISTS ck_api_keys_name_length;
ALTER TABLE agent.api_keys
    ADD CONSTRAINT ck_api_keys_name_length
        CHECK (char_length(name) BETWEEN 1 AND 64);

CREATE INDEX IF NOT EXISTS ix_api_keys_principal_created
    ON agent.api_keys (principal_id, created_at DESC);

INSERT INTO agent.schema_migrations (version, description)
VALUES (14, 'Name and lookup index for MCP personal access tokens')
ON CONFLICT (version) DO NOTHING;

COMMIT;
