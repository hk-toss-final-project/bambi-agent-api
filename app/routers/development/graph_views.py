"""에이전트 LangGraph 구조 시각화 페이지(/dev/graphs) 라우터.

세 에이전트 그래프(Personal Wiki·Report Generation·키워드 비서)의 구조를
Mermaid 차트로 렌더하는 개발 전용 HTML 페이지를 제공한다. 서버는 Mermaid
정의 텍스트만 만들고, 그리기는 브라우저의 mermaid.js(CDN)가 수행한다.

개발 API와 같은 게이트(require_development_access)를 쓰므로 local/test
환경에서 명시적으로 활성화했을 때만 접근할 수 있다. 사람이 보는 화면이라
OpenAPI 문서에는 올리지 않는다.
"""

from __future__ import annotations

import html

from fastapi import APIRouter, Depends, status
from fastapi.responses import HTMLResponse, PlainTextResponse

from app.exceptions import AgentApiError, ErrorDetail
from app.routers.development.routes import require_development_access
from app.services.graph_diagrams import get_graph_diagram, list_graph_diagrams

router = APIRouter(dependencies=[Depends(require_development_access)])

# 렌더에 쓰는 mermaid.js 버전. 개발 전용 페이지라 CDN 로드를 허용한다.
_MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs"

_PAGE_STYLE = """
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, "Apple SD Gothic Neo", "Segoe UI", sans-serif;
    margin: 0 auto; max-width: 960px; padding: 2rem 1.25rem 4rem;
  }
  h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }
  .subtitle { color: #667; margin-bottom: 2rem; }
  section {
    border: 1px solid rgba(127, 127, 127, 0.35); border-radius: 10px;
    padding: 1.25rem 1.5rem; margin-bottom: 2rem;
  }
  section h2 { font-size: 1.15rem; margin: 0 0 0.25rem; }
  .description { color: #667; font-size: 0.9rem; margin: 0 0 1rem; }
  .mermaid { display: flex; justify-content: center; }
  .raw-link { font-size: 0.8rem; }
  @media (prefers-color-scheme: dark) {
    .subtitle, .description { color: #99a; }
  }
"""


def _render_page() -> str:
    """그래프 3개를 모두 담은 시각화 페이지 HTML을 만든다."""
    sections: list[str] = []
    for diagram in list_graph_diagrams():
        sections.append(
            f"""
  <section id="{html.escape(diagram.slug)}">
    <h2>{html.escape(diagram.title)}</h2>
    <p class="description">{html.escape(diagram.description)}</p>
    <pre class="mermaid">{html.escape(diagram.mermaid)}</pre>
    <p class="raw-link">
      <a href="/dev/graphs/{html.escape(diagram.slug)}.mmd">Mermaid 원문 보기</a>
    </p>
  </section>"""
        )
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>에이전트 그래프 구조</title>
  <style>{_PAGE_STYLE}</style>
</head>
<body>
  <h1>에이전트 그래프 구조</h1>
  <p class="subtitle">LangGraph StateGraph 정의에서 추출한 실행 그래프입니다.
  점선은 조건부 분기를 뜻합니다.</p>
{"".join(sections)}
  <script type="module">
    import mermaid from "{_MERMAID_CDN}";
    mermaid.initialize({{ startOnLoad: true, securityLevel: "loose" }});
  </script>
</body>
</html>"""


@router.get("/graphs", response_class=HTMLResponse, include_in_schema=False)
async def show_graphs() -> HTMLResponse:
    """에이전트 그래프 3개를 Mermaid 차트로 렌더하는 페이지를 반환한다."""
    return HTMLResponse(_render_page())


@router.get(
    "/graphs/{slug}.mmd", response_class=PlainTextResponse, include_in_schema=False
)
async def show_graph_mermaid(slug: str) -> PlainTextResponse:
    """그래프 하나의 Mermaid 정의 원문을 반환한다(문서 첨부·공유용)."""
    diagram = get_graph_diagram(slug)
    if diagram is None:
        raise AgentApiError(
            status.HTTP_404_NOT_FOUND,
            ErrorDetail(code="GRAPH_NOT_FOUND", message="등록되지 않은 그래프입니다."),
        )
    return PlainTextResponse(diagram.mermaid)
