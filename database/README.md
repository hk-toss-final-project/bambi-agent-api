# Agent DB 로컬 실행

`agent-db`는 PostgreSQL 17과 pgvector를 사용합니다. Docker Compose는 DB가 시작될
때마다 `scripts/initialize_agent_db.sh`를 실행합니다. 먼저
`schema_migrations`에 없는 SQL을 파일명 순서대로 적용하고, 개발 Seed 파일의
합성 Checksum이 바뀌었으면 Publish Snapshot, 웹 클리핑과 사용자 URL Seed를
이어서 적용합니다.

자동 실행에는 Lifecycle Hook을 지원하는 Docker Compose 2.30 이상이 필요합니다.

## 시작

```bash
cp .env.example .env
```

`.env`에 `AGENT_DB_PASSWORD`와 애플리케이션이 사용할 `AGENT_DATABASE_URL`을 설정합니다.
로컬 DB에 개발 Seed가 필요 없으면 `AGENT_DB_APPLY_DEV_SEEDS=false`로 설정합니다.
비밀번호가 포함된 `.env`는 Git에서 제외됩니다.

```bash
docker compose up -d --wait agent-db
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

`dummy/clippings`의 Obsidian Web Clipper Markdown은 `mock-clipping-user`의 사용자
원본과 처리 대기 Job으로 저장됩니다. `wiki_documents`에는 Worker가 생성한 LLM Wiki만
들어가므로 Seed 직후에는 이 사용자의 Wiki 문서가 없습니다.

```sql
SELECT version.title, version.clipped_on, source.canonical_url, version.raw_content
FROM agent.user_source_document_versions AS version
JOIN agent.user_source_documents AS source ON source.id = version.source_document_id
WHERE source.user_id = 'mock-clipping-user'
ORDER BY version.clipped_on DESC, version.title;
```

`dummy/urls/url.txt`의 URL도 같은 사용자의 `wiki_source_events`와
`user_source_documents` Head로 등록됩니다. DB 초기화 과정에서는 외부 HTTP 요청을
하지 않으므로 본문 Version은 만들지 않으며, 기존에 Jina Reader로 수집한 이벤트 상태와
본문 Version이 있으면 Seed 재적용 후에도 보존합니다.

```sql
SELECT event.status, source.canonical_url, source.current_version
FROM agent.user_source_documents AS source
JOIN agent.wiki_source_events AS event
  ON event.user_id = source.user_id
 AND event.source_url = source.canonical_url
WHERE source.user_id = 'mock-clipping-user'
  AND source.source_type = 'url'
ORDER BY source.canonical_url;
```

등록된 URL의 Markdown 본문까지 실제로 수집하려면 `.env`에
`AGENT_DATABASE_URL`을 설정하고 별도 수집 스크립트를 실행합니다.

```bash
uv run python scripts/ingest_user_urls.py
```

### Personal Wiki Builder 실행

`.env`에 `AGENT_DATABASE_URL`과 `OPENAI_API_KEY`를 설정한 뒤 대기 Job 한 건을
증분 Wiki로 처리합니다. Worker는 Entity·Concept·Schema Version, 원본
출처 관계, Wiki Chunk·Embedding, Build Snapshot을 저장한 뒤 Job을 완료합니다.

```bash
uv run python -m workers.main --worker personal-wiki --limit 1
```

실제 LLM·Embedding API 비용이 발생하므로 처음에는 한 건만 처리해 결과를
검수합니다. 품질 벤치마크는 모델의 현재 토큰 단가를 직접 전달해
별도로 실행합니다.

```bash
uv run python bench/wiki_builder/run.py \
  --model gpt-4.1-mini \
  --input-cost-per-million <current-input-price> \
  --output-cost-per-million <current-output-price>
```

생성된 Wiki는 다음 SQL로 확인합니다.

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
WHERE document.namespace_key = 'user/mock-clipping-user'
  AND document.deleted_at IS NULL
ORDER BY document.file_path;
```

Agent API를 실행한 뒤에는 Obsidian 스타일 관계 Graph에서 같은 데이터를 확인할 수
있습니다. 화면에서 사용자 ID를 바꾸면 해당 Namespace를 다시 조회합니다.

```text
http://127.0.0.1:8000/wiki-graph?user_id=mock-clipping-user
```

Graph 원본 JSON은 `GET /internal/v1/users/{user_id}/wiki/graph`에서 조회합니다.

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
- Migration 파일은 `NNNN_description.sql` 형식으로 만들고 Transaction 안에서 같은
  번호를 `agent.schema_migrations`에 기록합니다.
- 로컬 Compose는 `post_start` Hook으로 매 기동 시 미적용 Migration과
  변경된 개발 Seed를 자동 적용합니다. Migration은 Advisory Lock을, Seed는
  볼륨 내 Checksum과 File Lock을 사용해 중복 적용을 막습니다.
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

## 자동 Migration과 초기화

새 Migration이나 Seed 파일을 받은 다른 PC에서도 기존 볼륨을 유지한 채 아래
명령만 실행하면 미적용 Version과 변경된 Seed가 자동 반영됩니다. 둘 중
하나라도 실패하거나 최신 상태가 확인되지 않으면 Health Check가 통과하지 않습니다.

```bash
git pull
docker compose up -d --wait agent-db
```

Runner를 수동으로 다시 확인하거나 실행할 수도 있습니다. 이미 적용된 Version은
건너뛰므로 반복 실행해도 같은 DDL을 다시 수행하지 않습니다.

```bash
docker compose exec -T -u postgres agent-db /bin/sh /usr/local/bin/run-agent-db-migrations
docker compose exec -T -u postgres agent-db /bin/sh /usr/local/bin/run-agent-db-migrations --check
```

Migration과 Seed 전체 초기화 경로는 다음 명령으로 수동 실행·검증할 수 있습니다.

```bash
docker compose exec -T -u postgres agent-db /bin/sh /usr/local/bin/initialize-agent-db
docker compose exec -T -u postgres agent-db /bin/sh /usr/local/bin/initialize-agent-db --check
```

`0004`는 `0003`에서 Wiki Version으로 분류했던 개인 웹 클리핑을
`user_source_documents`와 `user_source_document_versions`로 이관합니다. 이후
`wiki_documents`와 `wiki_document_versions`는 Worker가 생성한 LLM Wiki만 저장하고,
`wiki_document_sources`가 Wiki Version과 원본 Version을 연결합니다.

`0005`는 LLM Wiki를 `entities/*.md`, `concepts/*.md`, `schema/schema.md`로
식별할 수 있도록 `wiki_documents`에 문서 유형·논리 Key·파일 경로를
추가합니다. `wiki_document_relations`는 문서 Graph를,
`wiki_version_documents`는 특정 Wiki Build의 정확한 문서 Version 구성을 보존합니다.

```sql
SELECT document.document_kind,
       document.document_key,
       document.file_path,
       version.version,
       version.normalized_content
FROM agent.wiki_documents AS document
JOIN agent.wiki_document_versions AS version
  ON version.document_id = document.id
 AND version.version = document.current_version
WHERE document.namespace_key = 'user/{user_id}'
  AND document.deleted_at IS NULL
ORDER BY document.file_path;
```

목업 데이터를 다시 적용할 때는 다음 Seed를 순서대로 실행합니다. 두 번째 Seed는
기존 발행 시도 이력을 지우고 세 Snapshot을 `ready` 상태로 되돌립니다. 세 번째
Seed는 클리핑 Job과 Source Event를 `queued`, `received`로 되돌리고 해당 원본으로
생성한 Wiki·Chunk·Embedding과 Job 시도 이력을 삭제하므로 로컬 목업 데이터를 초기화해도
될 때만 실행합니다. 네 번째 Seed는 URL Event와 원본 문서 Head를 멱등 등록하며 이미
수집한 상태와 본문 Version은 변경하지 않습니다.

```bash
docker compose exec -T agent-db sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < database/seeds/0001_dev_publish_snapshots.sql
docker compose exec -T agent-db sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < database/seeds/0002_dev_publish_snapshot_batch.sql
docker compose exec -T agent-db sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < database/seeds/0003_dev_web_clippings.sql
docker compose exec -T agent-db sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < database/seeds/0004_dev_user_urls.sql
```

클리핑 Markdown이나 URL 목록을 추가·수정한 뒤에는 해당 생성 SQL을 갱신합니다.

```bash
uv run python scripts/generate_web_clipping_seed.py
uv run python scripts/generate_web_clipping_seed.py --check
uv run python scripts/generate_user_url_seed.py
uv run python scripts/generate_user_url_seed.py --check
```

개발 Seed는 DB 볼륨에 저장된 합성 Checksum과 현재 Seed 파일이 다를 때만
적용됩니다. 기존 볼륨에 Checksum이 없으면 다음 기동 시 한 번 적용됩니다.
`AGENT_DB_APPLY_DEV_SEEDS=false`로 설정하면 자동 Seed를 건너뜁니다. 개발 데이터를 모두
삭제해도 되는 경우에만 아래 명령으로 볼륨을 제거한 뒤 다시 시작합니다.

```bash
docker compose down --volumes
docker compose up -d --wait agent-db
```
