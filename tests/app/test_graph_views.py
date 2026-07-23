"""에이전트 그래프 시각화(/dev/graphs) 서비스·라우터 검증.

그래프 구조 추출은 DB·LLM·네트워크 없이 결정적으로 동작해야 한다 — Wiki·
Report 그래프 빌더가 빌드 시점에 연결을 쓰지 않는다는 전제(None 스텁)가
깨지면 여기서 잡힌다. 또한 agent/에 정의된 StateGraph 수와 레지스트리
항목 수를 대조해, 새 그래프의 등록 누락(AGENTS.md 규칙 10)을 차단한다.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.graph_diagrams import get_graph_diagram, list_graph_diagrams


def _dev_client() -> TestClient:
    """개발 라우터가 활성화된 TestClient를 만든다."""
    return TestClient(create_app(Settings(environment="test", enable_dev_agent_api=True)))


def test_list_graph_diagrams_extracts_all_agents_without_connection() -> None:
    """세 에이전트 그래프의 Mermaid 정의를 연결 없이 추출한다."""
    diagrams = {d.slug: d for d in list_graph_diagrams()}

    assert set(diagrams) == {"personal-wiki", "report-generation", "assistant"}
    assert "load_source" in diagrams["personal-wiki"].mermaid
    assert "load_context" in diagrams["report-generation"].mermaid
    assert "reformulate" in diagrams["assistant"].mermaid
    for diagram in diagrams.values():
        assert "-->" in diagram.mermaid  # 엣지가 최소 하나는 있어야 그래프다


def test_every_stategraph_definition_is_registered() -> None:
    """agent/의 모든 StateGraph 정의가 /dev/graphs 레지스트리에 등록돼야 한다.

    새 그래프를 만들고 등록을 빠뜨리면 여기서 실패한다. 절차는 AGENTS.md
    필수 규칙 10(에이전트 그래프 등록)과 .claude/skills/graph-registry를 따른다.
    """
    agent_root = Path(__file__).parents[2] / "agent"
    definitions = 0
    for path in sorted(agent_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        definitions += path.read_text(encoding="utf-8").count("StateGraph(")

    registered = len(list_graph_diagrams())
    assert definitions == registered, (
        f"agent/에 StateGraph 정의가 {definitions}개인데 그래프 시각화 레지스트리에는 "
        f"{registered}개만 등록돼 있습니다. app/services/graph_diagrams.py의 "
        "list_graph_diagrams()에 등록하세요 (AGENTS.md 필수 규칙 10 참고)."
    )


def test_get_graph_diagram_returns_none_for_unknown_slug() -> None:
    """등록되지 않은 slug는 None을 반환한다."""
    assert get_graph_diagram("no-such-graph") is None


def test_graphs_page_renders_all_diagrams() -> None:
    """/dev/graphs 페이지가 그래프 3개의 Mermaid 블록을 모두 담는다."""
    with _dev_client() as client:
        response = client.get("/dev/graphs")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert body.count('<pre class="mermaid">') == 3
    assert "Personal Wiki Build" in body
    assert "키워드 비서 리서치 에이전트" in body


def test_graph_mermaid_raw_endpoint_returns_plain_text() -> None:
    """/dev/graphs/{slug}.mmd 는 Mermaid 원문을 text/plain으로 반환한다."""
    with _dev_client() as client:
        response = client.get("/dev/graphs/report-generation.mmd")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text.lstrip().startswith("---")
    assert "load_context" in response.text


def test_graph_mermaid_raw_endpoint_rejects_unknown_slug() -> None:
    """등록되지 않은 slug는 404 GRAPH_NOT_FOUND로 응답한다."""
    with _dev_client() as client:
        response = client.get("/dev/graphs/unknown.mmd")

    assert response.status_code == 404
    assert response.json()["code"] == "GRAPH_NOT_FOUND"


def test_graphs_page_is_absent_without_dev_flag() -> None:
    """개발 API 플래그가 없으면 시각화 페이지도 등록되지 않는다."""
    with TestClient(create_app(Settings(environment="test"))) as client:
        assert client.get("/dev/graphs").status_code == 404
