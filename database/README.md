# Agent DB 로컬 실행

`agent-db`는 PostgreSQL 17과 pgvector를 사용합니다. Docker Compose는 최초 데이터 볼륨 생성 시 `migrations/0001_initial.sql`을 자동 적용합니다.

## 시작

```bash
cp .env.example .env
```

`.env`에 `AGENT_DB_PASSWORD`와 애플리케이션이 사용할 `AGENT_DATABASE_URL`을 설정합니다. 비밀번호가 포함된 `.env`는 Git에서 제외됩니다.

```bash
docker compose up -d agent-db
docker compose ps agent-db
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

개발 데이터를 모두 삭제해도 되는 경우에만 아래 명령으로 볼륨을 제거한 뒤 다시 시작합니다.

```bash
docker compose down --volumes
docker compose up -d agent-db
```
