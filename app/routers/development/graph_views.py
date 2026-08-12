"""에이전트 LangGraph 구조 시각화 페이지(/dev/graphs) 라우터.

네 에이전트 그래프의 구조를 Mermaid 차트로 렌더하고, 각 노드를 선택하면
기능 설명을 보여주는 읽기 전용 HTML 페이지를 제공한다. 서버는 Mermaid 정의와
설명 텍스트를 만들고, 그리기와 선택 동작은 브라우저가 수행한다.

서버 측 DB·LLM·외부 API를 호출하지 않으므로 개발 실행 API와 분리해 배포
환경에서도 제공한다. 등록 여부는 ENABLE_DEV_GRAPH_VIEWS로 제어하며, 사람이
보는 화면이라 OpenAPI 문서에는 올리지 않는다.
"""

from __future__ import annotations

import html

from fastapi import APIRouter, status
from fastapi.responses import HTMLResponse, PlainTextResponse

from app.exceptions import AgentApiError, ErrorDetail
from app.services.graph_diagrams import (
    GraphDiagram,
    get_graph_diagram,
    list_graph_diagrams,
)

router = APIRouter()

# 렌더에 쓰는 mermaid.js 버전. 읽기 전용 구조 화면은 브라우저에서 CDN으로 그린다.
_MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs"

_PAGE_STYLE = """
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, "Apple SD Gothic Neo", "Segoe UI", sans-serif;
    margin: 0 auto; max-width: 1240px; padding: 2rem 1.25rem 4rem;
  }
  h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }
  .subtitle { color: #667; margin-bottom: 2rem; }
  .graph-section {
    border: 1px solid rgba(127, 127, 127, 0.35); border-radius: 10px;
    padding: 1.25rem 1.5rem; margin-bottom: 2rem;
  }
  .graph-section h2 { font-size: 1.15rem; margin: 0 0 0.25rem; }
  .description { color: #667; font-size: 0.9rem; margin: 0 0 1rem; }
  .graph-layout {
    display: grid; grid-template-columns: minmax(0, 1fr) minmax(260px, 320px);
    gap: 1.25rem; align-items: start;
  }
  .graph-canvas { min-width: 0; overflow-x: auto; }
  .mermaid { display: flex; justify-content: center; min-width: max-content; }
  .mermaid .node { cursor: pointer; }
  .mermaid .node:focus { outline: none; }
  .mermaid .node:hover rect,
  .mermaid .node:hover circle,
  .mermaid .node:hover ellipse,
  .mermaid .node:hover polygon,
  .mermaid .node:focus rect,
  .mermaid .node:focus circle,
  .mermaid .node:focus ellipse,
  .mermaid .node:focus polygon,
  .mermaid .node.is-selected rect,
  .mermaid .node.is-selected circle,
  .mermaid .node.is-selected ellipse,
  .mermaid .node.is-selected polygon {
    stroke: #635bff !important; stroke-width: 3px !important;
  }
  .node-panel {
    border: 1px solid rgba(99, 91, 255, 0.35); border-radius: 10px;
    background: rgba(99, 91, 255, 0.06); min-height: 148px; padding: 1rem;
  }
  .node-kicker {
    color: #635bff; font-size: 0.7rem; font-weight: 700; letter-spacing: 0.08em;
    margin: 0 0 0.45rem; text-transform: uppercase;
  }
  .node-panel h3 { font-size: 1rem; margin: 0 0 0.5rem; }
  .node-panel p:last-child { font-size: 0.88rem; line-height: 1.55; margin: 0; }
  .node-id {
    background: rgba(99, 91, 255, 0.12); border-radius: 5px; display: inline-block;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.72rem;
    margin: 0 0 0.55rem !important; padding: 0.2rem 0.4rem;
  }
  .raw-link { font-size: 0.8rem; }
  @media (max-width: 820px) {
    .graph-layout { grid-template-columns: 1fr; }
    .node-panel { min-height: 120px; }
  }
  @media (prefers-color-scheme: dark) {
    .subtitle, .description { color: #99a; }
    .node-kicker { color: #aaa6ff; }
  }
"""


def _render_node_panel(diagram: GraphDiagram) -> str:
    """그래프 노드별 기능 설명을 우측 패널용 HTML로 만든다."""
    details = "".join(
        f"""
        <article class="node-detail" data-node-id="{html.escape(node.node_id)}" hidden>
          <p class="node-id">{html.escape(node.node_id)}</p>
          <h3>{html.escape(node.title)}</h3>
          <p>{html.escape(node.description)}</p>
        </article>"""
        for node in diagram.nodes
    )
    return f"""
      <aside class="node-panel" id="{html.escape(diagram.slug)}-node-panel"
             aria-live="polite" aria-label="선택한 노드 기능 설명">
        <div class="node-placeholder">
          <p class="node-kicker">Node details</p>
          <h3>노드를 선택하세요</h3>
          <p>왼쪽 그래프의 노드를 클릭하면 이곳에 해당 노드의 기능이 표시됩니다.</p>
        </div>
        {details}
      </aside>"""


def _render_page() -> str:
    """그래프 네 개와 노드 설명 패널을 담은 시각화 페이지 HTML을 만든다."""
    sections: list[str] = []
    for diagram in list_graph_diagrams():
        sections.append(
            f"""
  <section class="graph-section" id="{html.escape(diagram.slug)}">
    <h2>{html.escape(diagram.title)}</h2>
    <p class="description">{html.escape(diagram.description)}</p>
    <div class="graph-layout">
      <div class="graph-canvas">
        <pre class="mermaid">{html.escape(diagram.mermaid)}</pre>
        <p class="raw-link">
          <a href="/dev/graphs/{html.escape(diagram.slug)}.mmd">Mermaid 원문 보기</a>
        </p>
      </div>
      {_render_node_panel(diagram)}
    </div>
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
  점선은 조건부 분기를 뜻합니다. 노드를 선택하면 기능 설명을 확인할 수 있습니다.</p>
{"".join(sections)}
  <script type="module">
    import mermaid from "{_MERMAID_CDN}";
    mermaid.initialize({{ startOnLoad: false, securityLevel: "loose" }});
    await mermaid.run({{ querySelector: ".mermaid" }});

    const bindNodeDetails = (section) => {{
      const panel = section.querySelector(".node-panel");
      const placeholder = panel.querySelector(".node-placeholder");
      const details = Array.from(panel.querySelectorAll(".node-detail"));
      const nodeElements = Array.from(section.querySelectorAll(".mermaid .node"));
      const knownIds = details.map((detail) => detail.dataset.nodeId);

      const resolveNodeId = (nodeElement) => {{
        const label = nodeElement.querySelector(".nodeLabel")?.textContent?.trim();
        if (knownIds.includes(label)) return label;
        return knownIds
          .slice()
          .sort((left, right) => right.length - left.length)
          .find((nodeId) => nodeElement.id.includes(`-${{nodeId}}-`));
      }};

      const showDetails = (selectedElement, nodeId) => {{
        const selectedDetail = details.find(
          (detail) => detail.dataset.nodeId === nodeId
        );
        if (!selectedDetail) return;

        placeholder.hidden = true;
        details.forEach((detail) => {{ detail.hidden = detail !== selectedDetail; }});
        nodeElements.forEach((nodeElement) => {{
          const selected = nodeElement === selectedElement;
          nodeElement.classList.toggle("is-selected", selected);
          nodeElement.setAttribute("aria-pressed", String(selected));
        }});
      }};

      nodeElements.forEach((nodeElement) => {{
        const nodeId = resolveNodeId(nodeElement);
        if (!nodeId) return;
        nodeElement.setAttribute("role", "button");
        nodeElement.setAttribute("tabindex", "0");
        nodeElement.setAttribute("aria-controls", panel.id);
        nodeElement.setAttribute("aria-label", `${{nodeId}} 노드 기능 설명 보기`);
        nodeElement.setAttribute("aria-pressed", "false");
        nodeElement.addEventListener("click", () => showDetails(nodeElement, nodeId));
        nodeElement.addEventListener("keydown", (event) => {{
          if (event.key === "Enter" || event.key === " ") {{
            event.preventDefault();
            showDetails(nodeElement, nodeId);
          }}
        }});
      }});
    }};

    document.querySelectorAll(".graph-section").forEach(bindNodeDetails);
  </script>
</body>
</html>"""


@router.get("/graphs", response_class=HTMLResponse, include_in_schema=False)
async def show_graphs() -> HTMLResponse:
    """에이전트 그래프 네 개와 노드 기능 설명을 렌더하는 페이지를 반환한다."""
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
