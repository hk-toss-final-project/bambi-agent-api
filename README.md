# Bambi Agent API

이 저장소는 서버 두 개로 구성됩니다.

| | 파일 | 포트 | 상태 |
|---|---|---|---|
| **키워드 비서 웹 UI** | `app/assistant/main.py` | 8100 | ✅ 동작함 — 지금 실제로 쓰는 제품 |
| Agent API | `app/main.py` | 8000 | 🚧 스캐폴드 단계 — 대부분 미구현 |

## 키워드 비서 웹 UI (실제 제품)

키워드를 입력하면 관련 YouTube 영상 자막, Reddit 게시글을 LLM으로 요약하고, 어제
발행된 뉴스 기사를 중복 없이 모아 보여주는 브라우저용 비서입니다. 처음 조회하는
키워드는 폭넓게 보여주고, 이미 본 영상은 다음부터 제외합니다.

```bash
uv run uvicorn app.assistant.main:app --port 8100
# 브라우저에서 http://localhost:8100 접속
```

자세한 동작 방식은 [키워드 비서 개발 명세](docs/keyword-assistant.md)를 참고하세요.

### 두 서버 함께 실행

```bash
uv run python scripts/run_all.py
# Agent API      : http://127.0.0.1:8000
# 키워드 비서 UI : http://127.0.0.1:8100
```

## Agent API (스캐폴드 단계)

LangGraph 기반 에이전트를 FastAPI로 제공할 예정인 백엔드 API입니다. 전체 기능
명세 1~43절의 626개 기능을 코드 함수와 1:1로 매핑했고, 전용 MVP 문서의 71개
구현 대상에는 함수 바로 위에 `# MVP:` 주석을 표시했습니다. **현재 라우터와 기능
함수는 구조만 정의되어 있으며, 실제 기능 호출은 구현되지 않았습니다.**

각 기능 영역의 `api.py`는 공개 facade로만 사용하며, 실제 함수는 `features/`
구현 패키지에 역할별로 분리되어 있습니다.

```bash
uv run uvicorn app.main:app --port 8000 --reload
```

서버 실행 후 다음 API 문서를 사용할 수 있습니다.

- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc: <http://127.0.0.1:8000/redoc>
- OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>

Swagger UI는 최초 접속 시 시스템 테마를 따르며, 우측 상단 버튼으로 다크·라이트
모드를 전환할 수 있습니다. 선택한 테마는 브라우저에 저장됩니다.

내부 인증이 적용되기 전까지 API 문서를 외부 네트워크에 노출하지 마세요.
문서 노출이 필요 없는 환경에서는 `DOCS_ENABLED=false`로 비활성화할 수 있습니다.

로컬 PostgreSQL과 pgvector는 [database/README.md](database/README.md)의 안내에
따라 Docker Compose로 실행합니다. (키워드 비서 UI만 쓸 경우에는 필요 없습니다.)

### Agent API 문서

- [전체 기능 명세](docs/agent-api-feature-spec.md)
- [MVP 개발 범위](docs/agent-api-mvp-scope.md)
- [FastAPI MVP API 설계](docs/fastapi-mvp-api.md)
- [Agent DB 설계](docs/agent-db-design.md)
- [Agent DB 테이블 카탈로그](docs/agent-db-table-catalog.md)
- [Agent DB 컬럼 사전](docs/agent-db-column-dictionary.md)
- [프로젝트 구조와 기능 파일 매핑](docs/project-structure.md)

## 시작하기

```bash
uv sync
cp .env.example .env
```

`.env`를 열어 최소한 아래 값을 채웁니다.

- **`OPENAI_API_KEY`**: 키워드 비서의 자막·게시글·기사 요약에 필요합니다 (필수).
- `AGENT_DATABASE_URL`, `VECTOR_STORE_URL`, `QUEUE_URL` 등: Agent API 백엔드용입니다.
  키워드 비서 UI만 쓸 경우 비워둬도 됩니다.

## 검증

```bash
uv run pytest
uv run python -m compileall -q app agent domain infrastructure workers scheduler mcp_server shared main.py
```
