# Agent DB 로컬 실행

`agent-db`는 PostgreSQL 17과 pgvector를 사용합니다. DB 초기화 경로는 운영과
로컬에서 동일하게 **버전 Migration만** 적용하며, 개발용 더미 Seed는 자동
주입하지 않습니다.

## 시작

```bash
cp .env.example .env
```

`.env`에 `AGENT_DB_PASSWORD`와 애플리케이션이 사용할
`AGENT_DATABASE_URL`을 설정합니다. 비밀번호가 포함된 `.env`는 Git에서
제외됩니다.

```bash
./scripts/start_agent_db.sh
docker compose ps agent-db
```

`scripts/start_agent_db.sh`는 컨테이너를 실행하고
`scripts/initialize_agent_db.sh`를 명시적으로 호출한 뒤 Health 상태를
확인합니다. Compose `post_start`도 새 컨테이너 기동 시 같은 Initializer를
실행하지만, 이미 실행 중인 컨테이너에서는 `post_start`가 다시 실행되지 않으므로
Migration 파일을 받은 뒤에는 항상 아래 명령을 다시 실행합니다.

```bash
git pull
./scripts/start_agent_db.sh
```

자동 실행에는 Lifecycle Hook을 지원하는 Docker Compose 2.30 이상이 필요합니다.

## 서버와 Worker 확인

Agent API는 `AGENT_DATABASE_URL`이 설정되면 PostgreSQL에 연결합니다. 서버를
실행한 뒤 Swagger에서 실제 사용자와 작업 데이터를 이용해 API를 확인할 수 있습니다.

```bash
uv run uvicorn app.main:app --port 8000 --reload --loop app.main:selector_event_loop
```

```text
http://127.0.0.1:8000/docs
```

개인 Wiki 원본 URL을 개발 환경에서 직접 수집해야 한다면 사용자와 입력을
명시적으로 전달합니다. 이 스크립트는 DB 초기화나 배포 과정에서 자동 실행되지
않습니다.

```bash
uv run python scripts/ingest_user_urls.py \
  --user-id <user_id> \
  --url https://example.com/article
```

저장된 대기 Job은 Worker로 처리합니다. 이 명령은 실제 LLM·Embedding API 비용이
발생합니다.

```bash
uv run python -m workers.main --worker personal-wiki --limit 1
```

생성된 Wiki는 실제 사용자 Namespace로 확인합니다.

```sql
SELECT document.document_kind,
       document.document_key,
       document.file_path,
       version.version,
       version.title,
       version.normalized_content
FROM agent.wiki_documents AS document
JOIN agent.wiki_document_versions AS version
  ON version.document_id = document.id
 AND version.version = document.current_version
WHERE document.namespace_key = 'user/{user_id}'
  AND document.deleted_at IS NULL
ORDER BY document.file_path;
```

Graph 화면은 `http://127.0.0.1:8000/wiki-graph?user_id={user_id}`, 원본 JSON은
`GET /internal/v1/users/{user_id}/wiki/graph`에서 조회합니다.

## 스키마 계약 확인

```bash
docker compose exec -T agent-db sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < database/checks/0001_schema_contract.sql
docker compose exec -T agent-db sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < database/checks/0002_rls_contract.sql
```

## 마이그레이션 원칙

- 적용된 SQL 파일은 수정하지 않고 다음 순번 파일을 추가합니다.
- Migration 파일은 `NNNN_description.sql` 형식으로 만들고 Transaction 안에서
  같은 번호를 `agent.schema_migrations`에 기록합니다.
- Migration Runner는 PostgreSQL Advisory Lock으로 동시 실행을 막고, 적용 이력에
  없는 파일만 순서대로 실행합니다.
- 로컬 DB 시작 스크립트와 Compose `post_start`는 같은 Initializer를 사용합니다.
- 배포 환경에서는 API 시작 과정과 분리된 one-shot 작업으로 Initializer를 먼저
  실행합니다. 실패하면 API·Worker를 먼저 기동하지 않습니다.
- `vector`, `pg_trgm` 확장은 Cloud SQL Primary에서
  `cloudsqlsuperuser` 권한으로 먼저 생성합니다.
- 애플리케이션 계정은 테이블 소유자가 아니어야 하며 DML 최소 권한만 부여합니다.
- 개인 데이터 쿼리는 Transaction을 시작한 뒤 `app.user_id`와
  `app.access_scope`를 `SET LOCAL`로 지정합니다.

```sql
BEGIN;
SET LOCAL app.user_id = 'service-user-id';
SET LOCAL app.access_scope = 'user';
-- 사용자 범위 쿼리
COMMIT;
```

Scheduler나 시스템 관리 작업은 별도 권한을 가진 Worker 계정에서
`app.access_scope = 'system'`을 사용합니다.

## 수동 실행과 배포 one-shot

Runner와 Initializer는 반복 실행해도 이미 반영된 Migration을 건너뜁니다.

```bash
docker compose exec -T -u postgres agent-db /bin/sh /usr/local/bin/run-agent-db-migrations
docker compose exec -T -u postgres agent-db /bin/sh /usr/local/bin/run-agent-db-migrations --check
docker compose exec -T -u postgres agent-db /bin/sh /usr/local/bin/initialize-agent-db
docker compose exec -T -u postgres agent-db /bin/sh /usr/local/bin/initialize-agent-db --check
```

배포 이미지에서는 원격 DB URL과 Migration 경로만 지정합니다.

```bash
AGENT_DATABASE_URL=<postgresql-url> \
AGENT_DB_MIGRATION_DIR=/app/database/migrations \
AGENT_DB_MIGRATION_RUNNER_PATH=/app/scripts/run_agent_db_migrations.sh \
/bin/sh /app/scripts/initialize_agent_db.sh
```

## Migration 파일을 찾을 수 없다고 나올 때

호스트의 `database/migrations`에 파일이 있는데도
`Migration 파일을 찾을 수 없습니다: /opt/bambi/migrations`로 실패하면, 오래
실행된 컨테이너의 bind mount가 stale해진 경우입니다. 컨테이너 안의 mount를
확인한 뒤 컨테이너만 재생성합니다. DB 데이터는 named volume에 유지됩니다.

```bash
docker compose exec -T -u postgres agent-db ls /opt/bambi/migrations
docker compose up -d --force-recreate agent-db
./scripts/start_agent_db.sh
```
