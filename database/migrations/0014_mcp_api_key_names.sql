-- MCP Personal Access Token을 사용자가 식별할 수 있도록 이름과 조회 인덱스를 추가한다.

ALTER TABLE agent.api_keys
    ADD COLUMN name text NOT NULL DEFAULT 'MCP 연결';

ALTER TABLE agent.api_keys
    ALTER COLUMN name DROP DEFAULT;

ALTER TABLE agent.api_keys
    ADD CONSTRAINT ck_api_keys_name_length
        CHECK (char_length(name) BETWEEN 1 AND 64);

CREATE INDEX ix_api_keys_principal_created
    ON agent.api_keys (principal_id, created_at DESC);
