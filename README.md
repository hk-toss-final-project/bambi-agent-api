# Bambi Agent API

LangGraph 기반 에이전트를 FastAPI로 제공하는 API 서버 프로젝트입니다.

현재 저장소는 기능 구현 전 스캐폴드 단계입니다. 전체 기능 명세 1~43절의 626개 기능을 코드 함수와 1:1로 매핑했고, 전용 MVP 문서의 47개 구현 대상에는 함수 바로 위에 `# MVP:` 주석을 표시했습니다.

각 기능 영역의 `api.py`는 공개 facade로만 사용하며, 실제 함수는 `features/` 구현 패키지에 역할별로 분리되어 있습니다.

## 문서

- [전체 기능 명세](docs/agent-api-feature-spec.md)
- [MVP 개발 범위](docs/agent-api-mvp-scope.md)
- [프로젝트 구조와 기능 파일 매핑](docs/project-structure.md)

## 실행

```bash
uv run uvicorn app.main:app --reload
```

현재 라우터와 기능 함수는 구조만 정의되어 있으며, 실제 기능 호출은 구현되지 않았습니다.

## 검증

```bash
uv run pytest
uv run python -m compileall -q app agent domain infrastructure workers scheduler mcp_server shared main.py
```
