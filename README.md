# Report Builder Agent API

이 저장소는 **서버 한 개**로 구성됩니다.

| | 파일 | 포트 | 제공 |
|---|---|---|---|
| **Agent API** | `app/main.py` | 8000 | API(`/internal/v1/**`) + LLM Wiki Graph UI + 키워드 비서 웹 UI(`/assistant/**`) |

MVP 핵심 파이프라인: 클리핑/URL → LLM Wiki → 관심사 → 외부 수집 → Report Builder 생성 → 발행 Snapshot.

키워드 비서(`agent/assistant`)의 실시간 수집·선별은 Report Builder의 `REPORT-005`(Global
Source 검색)·`REPORT-006`(생성 자료 선별)에 연결되어 있습니다. 웹 UI와 Main API가 **같은
수집·선별 코드**를 쓰므로 두 경로의 결과가 갈라지지 않습니다.

비서 UI는 루트가 아니라 `/assistant` 하위에만 노출합니다(루트는 API 서버의 것입니다).
UI가 필요 없는 배포에서는 `ENABLE_ASSISTANT_UI=false`로 끌 수 있습니다.

기능별 구현 상태는 [MVP 구현 현황 체크리스트](docs/agent-api-mvp-scope.md)에서 확인합니다.

## 실행 방법

### 0. 공통 준비

```bash
uv sync
cp .env.example .env
```

`.env`에서 최소한 아래 값을 채웁니다.

- **`OPENAI_API_KEY`** — Wiki 빌드·Report Builder 생성·키워드 비서 요약에 필요 (필수)
- `AGENT_DATABASE_URL`, `AGENT_DB_PASSWORD` — Agent API·Worker용.
  키워드 비서 UI만 쓸 경우 비워둬도 됩니다.
- `ENABLE_DEV_AGENT_API=true` — Swagger 개발 실행 API(`/internal/v1/dev/**`)
  활성화. 로컬 개발 시 권장합니다.

### 1. PostgreSQL 실행 (Agent API 선행 조건)

```bash
docker compose up -d
```

시작 시 Migration과 개발 Seed(`mock-clipping-user` 데이터 포함)가 자동
적용됩니다. 자세한 절차는 [database/README.md](database/README.md)를
참고하세요. 키워드 비서 UI만 쓸 경우에는 필요 없습니다.

### 2. Agent API 서버 + Swagger

```bash
uv run uvicorn app.main:app --port 8000 --reload
```

- Swagger UI: <http://127.0.0.1:8000/docs> — 우측 상단 버튼으로 다크·라이트
  모드를 전환할 수 있고, 선택한 테마는 브라우저에 저장됩니다.
- ReDoc: <http://127.0.0.1:8000/redoc> · OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>
- `APP_ENV=local`(또는 `test`) + `ENABLE_DEV_AGENT_API=true`면 `dev-*` 태그의
  개발 실행 API가 함께 등록됩니다. 단계별 사용법은
  [Swagger 개발 테스트 가이드](docs/swagger-dev-guide.md)를 따라가세요.
- 내부 인증이 적용되기 전까지 API와 문서를 외부 네트워크에 노출하지 마세요.
  문서가 필요 없는 환경에서는 `DOCS_ENABLED=false`로 비활성화할 수 있습니다.

### 3. LLM Wiki Graph UI

Agent API 서버(8000)에 내장된 개인 지식 그래프 시각화 페이지입니다.

```text
http://127.0.0.1:8000/wiki-graph?user_id={user_id}
예) http://127.0.0.1:8000/wiki-graph?user_id=mock-clipping-user   ← 개발 Seed 사용자
```

- Entity(초록)·Concept(보라) Node 그래프, 검색·종류 필터, 확대·이동·Node
  Drag와 Markdown 상세 보기를 제공합니다.
- PostgreSQL이 필요하며, Wiki가 생성된 사용자만 그래프가 표시됩니다.
- 인증 없는 내부 개발 도구이므로 외부에 노출하지 마세요. 실제 서비스 화면은
  `GET /internal/v1/users/{user_id}/wiki/graph` JSON API를 소비해 프론트엔드가
  직접 렌더링합니다 ([Service 연동 가이드](docs/service-integration-guide.md) §3.6).

### 4. 키워드 비서 웹 UI

키워드를 입력하면 관련 YouTube 영상 자막, Reddit 게시글을 LLM으로 요약하고, 최근
뉴스 기사를 중복 없이 모아 브리핑으로 보여줍니다. 처음 조회하는 키워드는 폭넓게
보여주고, 이미 본 영상은 다음부터 제외합니다.

**API 서버와 같은 프로세스**에서 제공되므로 따로 띄우지 않습니다.

```bash
# 위 2번에서 띄운 서버 그대로 사용
# 브라우저에서 http://localhost:8000/assistant/ 접속
```

이 화면은 PostgreSQL 없이 동작하며 `OPENAI_API_KEY`만 필요합니다. DB 연결에 실패해도
서버는 기동하고 비서 UI는 그대로 쓸 수 있습니다(DB가 필요한 API만 `503
SERVICE_NOT_READY`로 응답합니다). 동작 방식은
[키워드 비서 개발 명세](docs/keyword-assistant.md)를 참고하세요.

### 5. Worker 실행

등록된 Agent Job(Wiki 빌드, Report Builder 생성)과 외부 수집을 처리하는 CLI입니다.
Wiki 빌드와 Report Builder 생성은 OpenAI를 실제 호출하므로 비용이 발생합니다.

| Worker | 용도 | 모드 |
|---|---|---|
| `personal-wiki` | 클리핑·URL 원본을 LLM Wiki로 빌드 (Chunk 포함, Embedding은 보류) | 단발 / `--loop` 상주 |
| `report-generation` | 생성 Job을 처리해 콘텐츠·발행 Snapshot 저장 | 단발 / `--loop` 상주 |
| `global-collector` | 키워드로 외부 기사 수집 (`--keywords` 필수, Provider 기본 `gdelt,naver`) | 단발 |
| `global-content` | 수집된 기사의 본문 확보 | 단발 |

```bash
# 단발: 대기 Job 한 Batch를 처리하고 종료
uv run python -m workers.main --worker personal-wiki
uv run python -m workers.main --worker report-generation

# 상주: Job이 생기면 자동 처리 (없으면 60초 간격으로 확인)
uv run python -m workers.main --worker report-generation --loop

# 외부 기사 수집 → 본문 확보
uv run python -m workers.main --worker global-collector --keywords "AI 에이전트,개인화"
uv run python -m workers.main --worker global-content
```

`--limit`, `--lease-seconds`, `--model`, `--interval-seconds`(상주 모드) 옵션으로
Batch 크기와 실행을 조정합니다. 상주 Worker는 `scheduled_at`이 도래한 Job만
Claim하므로 예약 생성 요청은 지정 시각에 처리됩니다.

## 구조

Agent API는 전체 기능 명세 1~43절의 기능 ID를 코드 함수와 1:1로 매핑하고,
전용 MVP 문서의 구현 대상 함수 위에 `# MVP:` 주석을 표시합니다. 각 기능
영역의 `api.py`는 공개 facade로만 사용하며, 실제 구현은 `features/` 패키지에
역할별로 분리되어 있습니다.

## Agent API 문서

- [전체 기능 명세](docs/agent-api-feature-spec.md)
- [MVP 개발 범위와 구현 현황 체크리스트](docs/agent-api-mvp-scope.md)
- [FastAPI MVP API 설계](docs/fastapi-mvp-api.md)
- [Swagger 개발 테스트 가이드](docs/swagger-dev-guide.md)
- [Service 연동 가이드 (service-api·service-worker)](docs/service-integration-guide.md)
- [Agent DB 설계](docs/agent-db-design.md)
- [Agent DB 테이블 카탈로그](docs/agent-db-table-catalog.md)
- [Agent DB 컬럼 사전](docs/agent-db-column-dictionary.md)
- [프로젝트 구조와 기능 파일 매핑](docs/project-structure.md)

## 검증

```bash
uv run pytest
uv run python -m compileall -q app agent domain infrastructure workers scheduler mcp_server shared main.py
```
