---
name: graph-registry
description: 새 LangGraph 에이전트(StateGraph)를 추가하거나 기존 그래프의 노드·엣지를 수정할 때, 그래프 시각화 페이지(/dev/graphs) 레지스트리를 함께 등록·갱신하는 절차. "에이전트 추가/만들어줘", "그래프 노드/엣지 수정", "StateGraph 변경", "새 워크플로 그래프" 같은 작업이면 반드시 이 스킬을 따른다.
---

# 에이전트 그래프 등록·갱신 절차

정본 규칙은 **AGENTS.md 필수 규칙 10 "에이전트 그래프 등록 (/dev/graphs)"** 이다.
이 스킬은 그 규칙을 실행 체크리스트로 옮긴 것이며, 내용이 어긋나면 AGENTS.md가 우선한다.

## 언제 실행하나

- `agent/` 아래에 새 `StateGraph`를 정의했을 때
- 기존 그래프의 노드·엣지·조건부 분기를 추가/삭제/이름 변경했을 때

노드 내부 구현만 바뀌고 그래프 구조(노드·엣지)가 그대로면 레지스트리 갱신은
필요 없다 — 단, 아래 체크리스트 4번(테스트)은 항상 실행한다.

## 체크리스트

1. **레지스트리 등록/갱신** — `app/services/graph_diagrams.py`의
   `list_graph_diagrams()`에 `GraphDiagram(slug, title, description, mermaid)`
   항목을 추가하거나 설명을 갱신한다.
   - slug: kebab-case (예: `personal-wiki`)
   - description: 한국어 노드 흐름 요약 (예: "원본 조회(load_source) → LLM 분류(classify) → …")
2. **None 스텁 안전성 확인** — 빌더가 DB 연결 등 인자를 받으면, 빌드 시점에
   그 인자를 실제로 사용하지 않는지 코드로 확인한 뒤 `builder(None)`으로
   구조만 추출한다. 빌드 시점에 인자가 필요해졌다면 임의로 우회하지 말고
   사용자와 처리 방식을 합의한다.
3. **facade 재노출** — 그래프 빌더를 해당 기능 영역 `api.py`에 재노출하고
   레지스트리는 facade에서만 import한다 (AGENTS.md 규칙 9).
4. **테스트 갱신·실행** — `tests/app/test_graph_views.py`의 기대 slug·노드명을
   갱신하고 `uv run pytest`를 실행한다. StateGraph 정의 수와 레지스트리 항목
   수를 대조하는 가드 테스트가 있어, 등록을 빠뜨리면 여기서 실패한다.
5. **렌더 확인** — 서버(`uv run uvicorn app.main:app --port 8000`)를 띄우고
   `/dev/graphs`에서 새/수정 그래프가 올바르게 그려지는지 확인한다.
   (`ENABLE_DEV_AGENT_API=true` + `APP_ENV=local|test` 필요)
