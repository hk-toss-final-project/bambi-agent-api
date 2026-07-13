# Bambi Agent API

LangGraph 기반 에이전트를 FastAPI로 제공하는 API 서버 프로젝트입니다.

현재 저장소는 기능 구현 전 스캐폴드 단계입니다. 전체 기능 명세 1~43절의 626개 기능을 코드 함수와 1:1로 매핑했고, 전용 MVP 문서의 47개 구현 대상에는 함수 바로 위에 `# MVP:` 주석을 표시했습니다.

각 기능 영역의 `api.py`는 공개 facade로만 사용하며, 실제 함수는 `features/` 구현 패키지에 역할별로 분리되어 있습니다.

## 문서

- [전체 기능 명세](docs/agent-api-feature-spec.md)
- [MVP 개발 범위](docs/agent-api-mvp-scope.md)
- [FastAPI MVP API 설계](docs/fastapi-mvp-api.md)
- [Agent DB 설계](docs/agent-db-design.md)
- [프로젝트 구조와 기능 파일 매핑](docs/project-structure.md)

## 실행

```bash
uv run uvicorn app.main:app --reload
```

서버 실행 후 다음 API 문서를 사용할 수 있습니다.

- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc: <http://127.0.0.1:8000/redoc>
- OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>

Swagger UI는 최초 접속 시 시스템 테마를 따르며, 우측 상단 버튼으로 다크·라이트
모드를 전환할 수 있습니다. 선택한 테마는 브라우저에 저장됩니다.

내부 인증이 적용되기 전까지 API 문서를 외부 네트워크에 노출하지 마세요.
문서 노출이 필요 없는 환경에서는 `DOCS_ENABLED=false`로 비활성화할 수 있습니다.

로컬 PostgreSQL과 pgvector는 [database/README.md](database/README.md)의 안내에 따라 Docker Compose로 실행합니다.

현재 라우터와 기능 함수는 구조만 정의되어 있으며, 실제 기능 호출은 구현되지 않았습니다.

## 검증

```bash
uv run pytest
uv run python -m compileall -q app agent domain infrastructure workers scheduler mcp_server shared main.py
```
