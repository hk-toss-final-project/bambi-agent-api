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
    """모든 에이전트 그래프의 Mermaid 정의를 연결 없이 추출한다."""
    diagrams = {d.slug: d for d in list_graph_diagrams()}

    assert set(diagrams) == {
        "personal-wiki",
        "wiki-maintenance-v2",
        "wiki-read-v2",
        "report-generation",
        "assistant",
        "change-history",
    }
    for node in (
        "load_source",
        "resolve_onboarding_context",
        "classify",
        "prepare_identity",
        "resolve_identity",
        "quality_gate",
        "recall_candidates",
        "link_relations",
        "plan",
        "validate_plan",
        "persist",
        "embed",
        "finalize",
    ):
        assert node in diagrams["personal-wiki"].mermaid
    assert "load_context" in diagrams["report-generation"].mermaid
    for node in (
        "restore_or_locate",
        "select_seed",
        "navigate",
        "search_global",
        "assess",
        "collect_live",
        "finalize",
    ):
        assert node in diagrams["wiki-read-v2"].mermaid
    for node in (
        "audit",
        "plan",
        "repair_derivatives",
        "full_rebuild",
        "finalize",
    ):
        assert node in diagrams["wiki-maintenance-v2"].mermaid
    # 토글이 켜졌을 때 generate를 대체하는 분기가 그래프에 실제로 있어야 한다.
    assert "change_history" in diagrams["report-generation"].mermaid
    assert "reformulate" in diagrams["assistant"].mermaid
    for node in ("prepare", "supervisor", "diff", "compose", "impact", "validate",
                 "assemble", "store"):
        assert node in diagrams["change-history"].mermaid
    for diagram in diagrams.values():
        assert "-->" in diagram.mermaid  # 엣지가 최소 하나는 있어야 그래프다


def test_every_graph_node_has_display_text() -> None:
    """시각화되는 시작·작업·종료 노드마다 제목과 기능 설명이 있어야 한다."""
    for diagram in list_graph_diagrams():
        node_ids = [node.node_id for node in diagram.nodes]

        assert node_ids[0] == "__start__"
        assert node_ids[-1] == "__end__"
        assert len(node_ids) == len(set(node_ids))
        for node in diagram.nodes:
            assert node.title.strip()
            assert node.description.strip()


def test_graph_descriptions_match_current_agent_contracts() -> None:
    """수동 그래프 설명이 최근 실행 계약의 핵심 분기를 유지해야 한다."""
    diagrams = {diagram.slug: diagram for diagram in list_graph_diagrams()}

    wiki_nodes = {node.node_id: node for node in diagrams["personal-wiki"].nodes}
    assert "OpenAI Batch Item" in wiki_nodes["embed"].description

    report = diagrams["report-generation"]
    report_nodes = {node.node_id: node for node in report.nodes}
    assert "wiki_search·wiki_read·search_pool" in report_nodes["research"].description
    assert "collect_live 도구" not in report.description
    assert "근거 없는 주제는 생성에서 제외" in report_nodes["load_context"].description
    assert "주제마다" in report_nodes["change_history"].description
    assert "전부 실패했을 때만 generate" in report_nodes["change_history"].description

    change_history = diagrams["change-history"]
    change_nodes = {node.node_id: node for node in change_history.nodes}
    assert "신규·갱신·유지 팩트 전체" in change_nodes["compose"].description
    assert "전부 유지면 impact를 건너" in change_nodes["supervisor"].description
    assert "신규·갱신 팩트만" in change_nodes["store"].description


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
    """/dev/graphs 페이지가 그래프와 모든 노드의 설명 패널을 담는다."""
    with _dev_client() as client:
        response = client.get("/dev/graphs")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert body.count('<pre class="mermaid">') == 6
    assert body.count('class="node-panel"') == 6
    assert body.count('class="node-detail"') == sum(
        len(diagram.nodes) for diagram in list_graph_diagrams()
    )
    assert "Personal Wiki Build" in body
    assert "Wiki Read Loop V2" in body
    assert "Wiki Maintenance Loop V2" in body
    assert "키워드 비서 리서치 에이전트" in body
    assert "변경점(Delta) 추적" in body
    assert 'data-node-id="load_source"' in body
    assert "원본과 기존 Wiki 조회" in body
    assert "노드를 선택하세요" in body


def test_graphs_page_binds_click_and_keyboard_node_selection() -> None:
    """렌더된 Mermaid 노드는 클릭과 키보드 선택으로 설명을 전환해야 한다."""
    with _dev_client() as client:
        response = client.get("/dev/graphs")

    body = response.text
    assert 'querySelectorAll(".mermaid .node")' in body
    assert 'nodeElement.setAttribute("tabindex", "0")' in body
    assert 'event.key === "Enter" || event.key === " "' in body
    assert 'nodeElement.addEventListener("click"' in body
    assert 'detail.hidden = detail !== selectedDetail' in body


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


def test_graphs_page_is_available_in_production() -> None:
    """읽기 전용 그래프 화면은 production 배포에서도 기본 제공해야 한다."""
    with TestClient(create_app(Settings(environment="production"))) as client:
        response = client.get("/dev/graphs")

    assert response.status_code == 200


def test_graphs_page_is_absent_when_explicitly_disabled() -> None:
    """그래프 화면 전용 플래그를 끄면 라우터를 등록하지 않는다."""
    settings = Settings(environment="production", enable_dev_graph_views=False)
    with TestClient(create_app(settings)) as client:
        assert client.get("/dev/graphs").status_code == 404


def test_production_graph_view_does_not_enable_dev_execution_api() -> None:
    """그래프 화면 공개가 production 동기 실행 API까지 활성화하면 안 된다."""
    settings = Settings(environment="production", enable_dev_agent_api=True)
    with TestClient(create_app(settings)) as client:
        graph_response = client.get("/dev/graphs")
        execution_response = client.post("/internal/v1/dev/jobs/test-job/run")

    assert graph_response.status_code == 200
    assert execution_response.status_code == 404
