# Agent DB 로컬 실행

`agent-db`는 PostgreSQL 17과 pgvector를 사용합니다. Docker Compose는 최초 데이터 볼륨 생성 시 `migrations/0001_initial.sql`, `migrations/0002_publish_snapshot_batches.sql`, `migrations/0003_web_clipping_markdown.sql`을 순서대로 적용하고, Service Worker API 연동용 개발 Seed 두 개를 이어서 적용합니다.

## 시작

```bash
cp .env.example .env
```

`.env`에 `AGENT_DB_PASSWORD`와 애플리케이션이 사용할 `AGENT_DATABASE_URL`을 설정합니다. 비밀번호가 포함된 `.env`는 Git에서 제외됩니다.

```bash
docker compose up -d agent-db
docker compose ps agent-db
```

Agent API는 `AGENT_DATABASE_URL`이 설정되면 Publish Snapshot 조회와 ACK를
PostgreSQL에 연결합니다. 로컬 Seed의 고정 식별자로 실제 API를 확인할 수 있습니다.

```bash
curl http://127.0.0.1:8000/internal/v1/publish-snapshots/mock-content-001
```

Swagger UI의 `service-worker` 태그에서도 Batch Claim과 ACK를 바로 실행할 수 있습니다.

```text
http://127.0.0.1:8000/docs
```

Batch Claim은 Seed로 준비된 3건의 전체 Snapshot Payload를 생성 시각 순으로 반환합니다.

```bash
curl -X POST http://127.0.0.1:8000/internal/v1/publish-snapshot-batches/claim \
  -H 'Content-Type: application/json' \
  -d '{"worker_id":"service-worker-local","limit":3,"lease_seconds":120}'
```

Seed Snapshot의 고정 계약은 다음과 같습니다.

| 필드 | 값 |
|---|---|
| `user_id` | `mock-user-001` ~ `mock-user-003` |
| `content_id` | `mock-content-001` ~ `mock-content-003` |
| `version` | `1` |
| `status` | `ready` |

발행 ACK는 조회 응답의 `version`과 `snapshot_hash`를 그대로 전달합니다.

```bash
curl -X POST http://127.0.0.1:8000/internal/v1/publish-snapshots/mock-content-001/ack \
  -H 'Content-Type: application/json' \
  -d '{"version":1,"snapshot_hash":"d3b07384d113edec49eaa6238ad5ff00d3b07384d113edec49eaa6238ad5ff00","status":"published"}'
```

스키마 계약은 다음 명령으로 확인합니다.

```bash
docker compose exec -T agent-db sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < database/checks/0001_schema_contract.sql
docker compose exec -T agent-db sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < database/checks/0002_rls_contract.sql
```

## 마이그레이션 원칙

- 적용된 SQL 파일은 수정하지 않고 다음 순번 파일을 추가합니다.
- 운영 마이그레이션은 Agent API 시작 과정이 아니라 별도 Cloud Run Job에서 한 번만 실행합니다.
- `vector`, `pg_trgm` 확장은 Cloud SQL Primary에서 `cloudsqlsuperuser` 권한으로 먼저 생성합니다.
- 애플리케이션 계정은 테이블 소유자가 아니어야 하며 DML 최소 권한만 부여합니다.
- 개인 데이터 쿼리는 트랜잭션을 시작한 뒤 `app.user_id`와 `app.access_scope`를 `SET LOCAL`로 지정합니다.

```sql
BEGIN;
SET LOCAL app.user_id = 'service-user-id';
SET LOCAL app.access_scope = 'user';
-- 사용자 범위 쿼리
COMMIT;
```

Scheduler나 시스템 관리 작업은 별도 권한을 가진 Worker 계정에서 `app.access_scope = 'system'`을 사용합니다.

## 초기화

Migration과 개발 Seed는 Docker Entry Point에서 빈 Volume에만 자동 실행됩니다. 기존
볼륨에는 아직 적용하지 않은 Migration을 Version 순서대로 한 번씩 적용합니다.

```bash
docker compose exec -T agent-db sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < database/migrations/0002_publish_snapshot_batches.sql
docker compose exec -T agent-db sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < database/migrations/0003_web_clipping_markdown.sql
```

`0003`은 웹 클리퍼의 Markdown Frontmatter를 `wiki_document_versions`의 정식
컬럼으로 저장합니다. `title`과 Markdown 본문은 기존 `title`,
`normalized_content`를 사용하고, `source` URL은 부모 `wiki_documents.canonical_url`에
저장합니다.

목업 데이터를 다시 적용할 때는 다음 두 Seed를 순서대로 실행합니다. 두 번째 Seed는
기존 발행 시도 이력을 지우고 세 Snapshot을 `ready` 상태로 되돌리므로 로컬 연동
데이터를 초기화해도 될 때만 실행합니다.

```bash
docker compose exec -T agent-db sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < database/seeds/0001_dev_publish_snapshots.sql
docker compose exec -T agent-db sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < database/seeds/0002_dev_publish_snapshot_batch.sql
```

개발 데이터를 모두 삭제해도 되는 경우에만 아래 명령으로 볼륨을 제거한 뒤 다시 시작합니다.

```bash
docker compose down --volumes
docker compose up -d agent-db
```
