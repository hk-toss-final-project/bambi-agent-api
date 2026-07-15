"""개인 Wiki Graph API와 시각화 페이지를 검증한다."""

from collections.abc import Mapping
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import AppContainer
from app.main import create_app
from app.services.mvp import AgentApiMvpService
from app.services.wiki_graph import WikiGraphService


class _FakeGraphRepository:
    """결정적인 Entity·Concept 관계를 반환하는 Graph Repository 대역."""

    async def get_graph(self, user_id: str) -> Mapping[str, object]:
        """라우터 검증용 Wiki Graph를 반환한다."""
        updated_at = datetime(2026, 7, 15, tzinfo=UTC)
        return {
            "user_id": user_id,
            "namespace_key": f"user/{user_id}",
            "wiki_version": 3,
            "generated_at": updated_at,
            "stats": {
                "node_count": 2,
                "edge_count": 1,
                "entity_count": 1,
                "concept_count": 1,
                "orphan_count": 0,
            },
            "nodes": [
                {
                    "id": "entity-1",
                    "document_kind": "entity",
                    "document_key": "obsidian",
                    "title": "Obsidian",
                    "subtype": "product",
                    "summary": "지식 관리 도구",
                    "aliases": ["옵시디언"],
                    "file_path": "entities/obsidian.md",
                    "version": 2,
                    "updated_at": updated_at,
                    "markdown": "## Description\n지식 관리 도구",
                    "degree": 1,
                },
                {
                    "id": "concept-1",
                    "document_kind": "concept",
                    "document_key": "연결-노트",
                    "title": "연결 노트",
                    "subtype": "method",
                    "summary": "노트 연결 방법",
                    "aliases": [],
                    "file_path": "concepts/연결-노트.md",
                    "version": 1,
                    "updated_at": updated_at,
                    "markdown": "## Definition\n노트 연결 방법",
                    "degree": 1,
                },
            ],
            "edges": [
                {
                    "id": "entity-1:applies_concept:concept-1",
                    "source": "entity-1",
                    "target": "concept-1",
                    "relation_type": "applies_concept",
                    "metadata": {},
                }
            ],
        }


def _graph_client() -> TestClient:
    """가짜 Graph 저장소가 연결된 FastAPI TestClient를 만든다."""
    settings = Settings(app_name="Wiki Graph Test", environment="test")
    container = AppContainer(
        settings=settings,
        mvp_service=AgentApiMvpService(),
        wiki_graph_service=WikiGraphService(_FakeGraphRepository()),
    )
    return TestClient(create_app(settings, container))


def test_wiki_graph_api_returns_nodes_edges_and_stats() -> None:
    """Graph API가 PWIKI-003 Node·Edge·집계 계약을 반환한다."""
    with _graph_client() as client:
        response = client.get("/internal/v1/users/user-1/wiki/graph")

    assert response.status_code == 200
    assert response.json()["feature_id"] == "PWIKI-003"
    assert response.json()["stats"]["node_count"] == 2
    assert response.json()["nodes"][0]["title"] == "Obsidian"
    assert response.json()["edges"][0]["relation_type"] == "applies_concept"


def test_wiki_graph_api_requires_database_service(client: TestClient) -> None:
    """DB가 없는 Runtime은 Graph 조회 성공 대신 SERVICE_NOT_READY를 반환한다."""
    response = client.get("/internal/v1/users/user-1/wiki/graph")

    assert response.status_code == 503
    assert response.json()["code"] == "SERVICE_NOT_READY"


def test_wiki_graph_page_contains_local_interactive_graph(client: TestClient) -> None:
    """시각화 페이지가 외부 CDN 없이 검색·필터·상세 Graph UI를 포함한다."""
    response = client.get("/wiki-graph?user_id=mock-clipping-user")

    assert response.status_code == 200
    assert "Bambi Wiki Graph" in response.text
    assert 'id="graph-search"' in response.text
    assert 'id="filter-entity"' in response.text
    assert 'id="detail-markdown"' in response.text
    assert "requestAnimationFrame(simulate)" in response.text
    assert "https://cdn" not in response.text


def test_wiki_graph_page_hides_completed_loading_status(client: TestClient) -> None:
    """로딩 완료 시 status 레이어의 display 규칙이 hidden 속성을 덮어쓰지 않는다."""
    response = client.get("/wiki-graph?user_id=mock-clipping-user")

    assert response.status_code == 200
    assert ".status[hidden] { display: none !important; }" in response.text


def test_wiki_graph_page_escapes_initial_user_id(client: TestClient) -> None:
    """초기 사용자 ID가 HTML 속성에 Script로 주입되지 않도록 Escape한다."""
    response = client.get("/wiki-graph", params={"user_id": '<script>alert(1)</script>'})

    assert response.status_code == 200
    assert '<script>alert(1)</script>' not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
