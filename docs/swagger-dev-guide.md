# Swagger 개발 테스트 가이드

이 문서는 로컬 Swagger에서 아래 흐름을 직접 검증하는 방법을 설명합니다.

```text
Source 저장 → Wiki 생성 → 관심사 추출 → 외부 문서 수집 → Report Builder 생성 → 결과 조회
```

`/internal/v1/dev/**` API는 운영용 등록 API를 대체하지 않습니다. 운영 API가
등록한 작업을 같은 코드로 즉시 실행하거나, 전체 흐p름을 한 번에 연결하는 테스트
용도입니다.

## 1. 실행 준비

`.env`에 최소한 아래 값을 설정합니다.

```dotenv
APP_ENV=local
DOCS_ENABLED=true
ENABLE_DEV_AGENT_API=true

AGENT_DATABASE_URL=postgresql://report_agent:<password>@127.0.0.1:5432/report_agent
AGENT_DB_PASSWORD=<password>

OPENAI_API_KEY=<openai-api-key>
WIKI_LLM_MODEL=gpt-4.1-mini
REPORT_LLM_MODEL=gpt-4.1-mini

# 선택 사항. 설정하면 모든 /dev 요청에 이 값을 헤더로 보내야 합니다.
DEV_AGENT_API_TOKEN=<local-test-token>
DEV_AGENT_TIMEOUT_SECONDS=180
```

- `APP_ENV`는 `local` 또는 `test`여야 합니다.
- `ENABLE_DEV_AGENT_API=true`가 아니면 `/internal/v1/dev/**` 경로가 등록되지 않습니다.
- Wiki와 Report Builder 생성은 OpenAI API를 실제 호출하므로 비용이 발생합니다.
- URL 수집은 Jina를 사용합니다. `JINA_API_TOKEN`을 생략하면 익명 호출을 시도합니다.
- GDELT는 별도 키가 없고, Naver와 NewsAPI는 각 API 자격 증명이 필요합니다.

DB와 API를 실행합니다.

```bash
docker compose up -d
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Swagger는 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)에서 엽니다.
`dev-jobs`, `dev-wiki`, `dev-interests`, `dev-global`, `dev-reports`,
`dev-scenarios`, `dev-workers` 태그가 보이면 개발 API가 활성화된 상태입니다.

`DEV_AGENT_API_TOKEN`을 설정했다면 각 `/dev` 호출에 다음 헤더를 보냅니다.

```http
X-Dev-Token: <local-test-token>
```

## 2. 권장 테스트 순서

### 2.1 사용자 Context 저장

`PUT /internal/v1/users/swagger-user-001/context`

```json
{
  "context_version": 1,
  "plan": "free",
  "preferred_language": "ko",
  "personalization_enabled": true,
  "blocked_interest_ids": [],
  "blocked_source_ids": []
}
```

`context_version`은 사용자별로 증가해야 합니다. 이미 `1`을 저장했다면 `2` 이상을
보냅니다. 같은 버전을 다시 보내면 `STALE_CONTEXT_VERSION`이 반환됩니다.

### 2.2 클리핑 저장 및 Wiki 작업 등록

`POST /internal/v1/users/swagger-user-001/wiki-sources/clippings`

```json
{
  "source_event_id": "swagger-clipping-001",
  "source": "https://example.com/report-builder/storage",
  "title": "Report Builder 저장 구조",
  "author": "Report Builder Team",
  "published": "2026-07-20T09:00:00+09:00",
  "created": "2026-07-20",
  "description": "Report Builder의 저장 구조를 설명한다.",
  "tags": ["report-builder", "database"],
  "content": "# Report Builder 저장 구조\n\n클리핑과 생성된 Wiki는 서로 다른 테이블에 저장된다."
}
```

응답의 `job_id`, `source_document_id`, `source_document_version_id`를 기록합니다.
클리핑 본문은 `user_source_document_versions`에 저장되고, 응답의 `job_id`는
`personal_wiki_build` 작업입니다.

### 2.3 Wiki 작업 즉시 실행

등록 응답의 `job_id`를 다음 경로에 넣습니다.

`POST /internal/v1/dev/jobs/{job_id}/run`

사용자와 작업 유형까지 함께 검증하려면 아래 API를 사용합니다.

`POST /internal/v1/dev/users/swagger-user-001/wiki-builds`

```json
{
  "job_id": "2.2에서 받은 job_id"
}
```

성공 결과에는 다음 값이 포함됩니다.

```json
{
  "status": "completed",
  "stages": [
    {"name": "wiki_build", "status": "completed", "duration_ms": 1234}
  ],
  "result": {
    "wiki_version_id": "...",
    "wiki_version": 1,
    "chunk_count": 3,
    "extracted_relation_count": 2,
    "stored_relation_count": 4,
    "isolated_node_count": 1,
    "relation_warnings": [],
    "affected_documents": []
  }
}
```

`extracted_relation_count`는 이번 원문에서 근거 검증을 통과한 관계 수이고,
`stored_relation_count`는 사용자 Namespace에 저장된 전체 Edge 수입니다. 노드가
여러 개인데 관계를 찾지 못했거나 잘못된 참조·근거를 제외했다면
`isolated_node_count`와 `relation_warnings`를 함께 확인합니다.

HTTP 상태만 보지 말고 최상위 `status`도 확인합니다. 실행 중 실패는 HTTP 200과
`status: "failed"`, `failed_stage`, 단계별 오류 코드로 반환될 수 있습니다.

`job_id`를 하나씩 넣지 않고 사용자의 대기 Job을 한 번에 처리할 수도 있습니다.

`POST /internal/v1/dev/users/swagger-user-001/wiki-builds/run-pending`

```json
{
  "limit": 10
}
```

대기 중(`queued` 또는 Lease가 만료된 `running`)인 `personal_wiki_build` Job을
우선순위 순서로 모아 순차 실행하고, Job별 결과를 `items`에 담아
`completed_count`, `failed_count`, `skipped_count`로 집계합니다. 다른 Worker가
먼저 가져간 Job은 실패가 아니라 `skipped`로 기록됩니다.

### 2.4 생성된 Wiki 조회

```text
GET /internal/v1/users/swagger-user-001/wiki/documents
GET /internal/v1/users/swagger-user-001/wiki/documents/{document_id}
GET /internal/v1/users/swagger-user-001/wiki/versions/{wiki_version_id}
GET /internal/v1/users/swagger-user-001/wiki/graph
GET /internal/v1/users/swagger-user-001/wiki/graph/top-nodes?limit=10
```

`document_kind`가 `entity`, `concept`, `schema` 중 하나인지, 상세 응답에 Source와
관계가 연결됐는지 확인합니다.

`top-nodes`는 현재 Graph에서 연결 Edge가 많은 순서(동률이면 제목순)로
Entity·Concept Node를 반환합니다. 각 항목에 `rank`와 `degree`가 포함되고
Markdown 본문은 제외한 경량 응답이므로, 사용자의 핵심 키워드를 뽑는 용도로
사용합니다.

### 2.5 관심사 재계산 및 조회

`POST /internal/v1/dev/users/swagger-user-001/interest-profiles/rebuild`

```json
{
  "limit": 20
}
```

저장된 결과는 다음 경로에서 다시 조회합니다.

```text
GET /internal/v1/users/swagger-user-001/interests
```

### 2.6 관련 외부 문서 수집

`POST /internal/v1/dev/users/swagger-user-001/latest-information`

관심사 결과를 사용하려면 `keywords`를 비웁니다.

```json
{
  "keywords": [],
  "providers": ["gdelt"],
  "language": "en",
  "limit_per_provider": 5
}
```

특정 검색어를 직접 지정할 수도 있습니다.

```json
{
  "keywords": ["knowledge graph", "personalization"],
  "providers": ["gdelt"],
  "language": "en",
  "limit_per_provider": 5
}
```

Provider 하나가 실패해도 다른 Provider의 결과는 저장될 수 있습니다. `items`뿐 아니라
`provider_failures`도 함께 확인합니다.

### 2.7 Report Builder 생성

`POST /internal/v1/dev/users/swagger-user-001/report-generations`

```json
{
  "idempotency_key": "swagger-generation-001",
  "topic": "개인 지식 그래프와 콘텐츠 개인화",
  "content_type": "article",
  "language": "ko"
}
```

이 API는 `generation_requests`와 작업을 등록하고, 개인 Wiki와 외부 문서를 검색한
뒤 생성 결과까지 저장합니다. 응답의 `result.content_candidate_id`를 기록합니다.

### 2.8 생성 결과 조회

```text
GET /internal/v1/users/swagger-user-001/generated-contents
GET /internal/v1/users/swagger-user-001/generated-contents/{content_candidate_id}
```

상세 응답에서 다음 값을 확인합니다.

- `generation_request_id`, `generation_run_id`
- `title`, `summary`, `body`, `snapshot_hash`
- `citations[].document_version_id`, `citations[].chunk_id`
- `citations[].reference`: 개인 Wiki는 `P1`, `P2`, 외부 문서는 `G1`, `G2`

## 3. URL 입력 테스트

클리핑 대신 URL을 등록할 때는 다음 API를 호출합니다.

`POST /internal/v1/users/swagger-user-001/wiki-sources/urls`

```json
{
  "source_event_id": "swagger-url-001",
  "url": "https://example.com/article",
  "memo": "Swagger URL 수집 테스트"
}
```

URL은 두 단계로 처리합니다.

1. 응답의 `job_id`를 `POST /internal/v1/dev/jobs/{job_id}/run`으로 실행합니다.
2. 결과의 `wiki_build_job_id`를 같은 API로 한 번 더 실행합니다.

첫 번째 작업은 Jina로 본문을 가져와 `user_source_document_versions`에 저장하고,
두 번째 작업은 저장된 본문으로 Wiki를 만듭니다. 본문이 이전 버전과 같으면 첫 번째
결과에 `unchanged: true`가 반환되고 새 Wiki 작업이 없을 수 있습니다.

등록된 URL이 여러 개면 Job ID 없이 Worker 방식으로 한 번에 실행할 수 있습니다.

`POST /internal/v1/dev/workers/url-collections/run`

```json
{
  "user_id": "swagger-user-001",
  "limit": 10
}
```

`user_id`를 생략하면 전체 사용자의 대기 URL 수집 Job을 대상으로 합니다. 각 Job은
Jina로 본문을 저장하고, 내용이 바뀐 경우 후속 `wiki_build_job_id`를 결과에
등록합니다. 이어서 `POST /internal/v1/dev/users/{user_id}/wiki-builds/run-pending`을
호출하면 등록된 Wiki 작업까지 한 번에 처리됩니다.

## 4. 전체 시나리오 한 번에 실행

개별 단계가 모두 동작한 뒤에는 다음 API로 전체 회귀 테스트를 실행합니다.

`POST /internal/v1/dev/users/swagger-user-002/scenarios/source-to-content`

```json
{
  "context": {
    "context_version": 1,
    "plan": "free",
    "preferred_language": "ko",
    "personalization_enabled": true,
    "blocked_interest_ids": [],
    "blocked_source_ids": []
  },
  "source": {
    "type": "clipping",
    "source_event_id": "swagger-scenario-001",
    "source": "https://example.com/report-builder/scenario",
    "title": "전체 시나리오 테스트",
    "created": "2026-07-20",
    "tags": ["report-builder", "swagger"],
    "content": "# 전체 시나리오\n\nSource에서 Wiki와 관심사를 만들고 Report Builder 콘텐츠를 생성한다."
  },
  "interest_limit": 20,
  "latest": {
    "keywords": ["personal knowledge graph"],
    "providers": ["gdelt"],
    "language": "en",
    "limit_per_provider": 5
  },
  "generation": {
    "idempotency_key": "swagger-scenario-generation-001",
    "topic": "개인 지식 그래프로 콘텐츠를 개인화하는 방법",
    "content_type": "article",
    "language": "ko"
  }
}
```

URL 시나리오는 `source`만 아래처럼 바꿉니다.

```json
{
  "type": "url",
  "source_event_id": "swagger-scenario-url-001",
  "url": "https://example.com/article",
  "memo": "전체 URL 시나리오"
}
```

응답에서 아래 단계가 순서대로 완료되는지 확인합니다.

```text
context → source_ingestion → (URL일 때 url_collection) → wiki_build
→ interest_extraction → latest_collection → report_generation
```

`result`에는 `source_document_version_id`, `wiki_version_id`,
`interest_profile_id`, `generation_job_id`, `content_candidate_id`가 함께 반환됩니다.

## 5. 재실행 규칙

| 값 | 같은 작업 재확인 | 새 작업 실행 |
|---|---|---|
| `context_version` | Context를 생략 | 이전보다 크게 증가 |
| `source_event_id` | 같은 값 유지 | 새 값 사용 |
| `idempotency_key` | 같은 값 유지 | 새 값 사용 |

완료된 `job_id`를 다시 실행하면 저장된 결과와 `skipped` 단계가 반환될 수 있습니다.
전체 시나리오를 그대로 다시 실행할 때 Context까지 포함하면 버전 충돌이 먼저 나므로,
Context를 생략하거나 `context_version`을 증가시킵니다.

## 6. 오류 확인

| 증상 | 확인할 항목 |
|---|---|
| Swagger에 `dev-*` 태그가 없음 | `APP_ENV=local`, `ENABLE_DEV_AGENT_API=true` 확인 후 재시작 |
| `/dev` 호출이 `401` | `X-Dev-Token`이 설정과 같은지 확인 |
| 앱 시작 실패 | PostgreSQL 상태와 `AGENT_DATABASE_URL` 확인 |
| Wiki 또는 Report Builder 단계 실패 | `OPENAI_API_KEY`, 모델명, `failed_stage` 확인 |
| URL 수집 실패 | 대상 URL 접근 가능 여부와 Jina 응답 확인 |
| 외부 문서가 없음 | `provider_failures`, 검색어, 언어, Provider 키 확인 |
| `JOB_NOT_RUNNABLE` | 작업이 이미 실행 중인지 확인하고 lease 만료 후 재실행 |
| `STALE_CONTEXT_VERSION` | 이전보다 큰 버전으로 다시 저장 |

기본 실행 제한 시간은 180초입니다. 필요하면 `DEV_AGENT_TIMEOUT_SECONDS`를 최대
900초까지 늘릴 수 있습니다.

## 7. 미구현 계약 API (501 응답)

다음 API는 키워드 비서 웹 UI(`app/assistant`)에 구현된 동작을 Agent API로 옮기기
전에 요청·응답 계약만 Swagger에 먼저 공개한 것입니다. 호출하면 항상
`501 NOT_IMPLEMENTED`를 반환하며, 이는 실행 실패가 아니라 의도된 동작입니다.

| Method / Path | 계약 |
|---|---|
| `POST /internal/v1/dev/workers/latest-news/run` | 키워드로 외부 뉴스 API를 호출해 최신 기사를 Global 문서로 저장하는 Worker |
| `POST /internal/v1/dev/users/{user_id}/wiki-keyword-latest-information` | Wiki에서 연결이 많은 Node 순서로 키워드를 만들어 최신 정보를 검색·저장 |
| `POST /internal/v1/dev/users/{user_id}/insight-generations` | 개인 Wiki와 저장된 최신 정보로 요약·인사이트 콘텐츠 생성 |

Swagger에서는 summary 앞의 `[미구현]` 표시로 구분할 수 있습니다.
