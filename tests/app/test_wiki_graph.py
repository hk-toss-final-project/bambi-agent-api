"""개인 Wiki Graph API와 시각화 페이지를 검증한다."""

from collections.abc import Mapping
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import AppContainer
from app.main import create_app
from app.services.wiki_graph import WikiGraphService
from tests.conftest import TEST_AUTHORIZATION_HEADER, TEST_INTERNAL_TOKEN


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


class _FakeRankedGraphRepository:
    """연결 수가 서로 다른 세 Node를 뒤섞인 순서로 반환하는 Graph 대역."""

    async def get_graph(self, user_id: str) -> Mapping[str, object]:
        """연결 상위 정렬 검증용 Wiki Graph를 반환한다."""
        updated_at = datetime(2026, 7, 19, tzinfo=UTC)

        def _node(
            node_id: str, kind: str, key: str, title: str, degree: int
        ) -> dict[str, object]:
            """검증에 필요한 필드만 다른 Graph Node를 만든다."""
            return {
                "id": node_id,
                "document_kind": kind,
                "document_key": key,
                "title": title,
                "subtype": "product" if kind == "entity" else "method",
                "summary": f"{title} 요약",
                "aliases": [],
                "file_path": f"{kind}s/{key}.md",
                "version": 1,
                "updated_at": updated_at,
                "markdown": f"## {title}",
                "degree": degree,
            }

        return {
            "user_id": user_id,
            "namespace_key": f"user/{user_id}",
            "wiki_version": 5,
            "generated_at": updated_at,
            "stats": {
                "node_count": 3,
                "edge_count": 2,
                "entity_count": 2,
                "concept_count": 1,
                "orphan_count": 0,
            },
            "nodes": [
                _node("concept-b", "concept", "나-개념", "나 개념", 1),
                _node("entity-c", "entity", "다-엔티티", "다 엔티티", 1),
                _node("entity-a", "entity", "가-엔티티", "가 엔티티", 2),
            ],
            "edges": [
                {
                    "id": "entity-a:applies_concept:concept-b",
                    "source": "entity-a",
                    "target": "concept-b",
                    "relation_type": "applies_concept",
                    "metadata": {},
                },
                {
                    "id": "entity-a:entity_relation:entity-c",
                    "source": "entity-a",
                    "target": "entity-c",
                    "relation_type": "entity_relation",
                    "metadata": {},
                },
            ],
        }


def _graph_client(repository: object | None = None) -> TestClient:
    """가짜 Graph 저장소가 연결된 FastAPI TestClient를 만든다."""
    settings = Settings(
        app_name="Wiki Graph Test",
        environment="test",
        internal_api_token=TEST_INTERNAL_TOKEN,
    )
    container = AppContainer(
        settings=settings,
        wiki_graph_service=WikiGraphService(repository or _FakeGraphRepository()),
    )
    client = TestClient(create_app(settings, container))
    client.headers.update(TEST_AUTHORIZATION_HEADER)
    return client


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


def test_wiki_top_nodes_api_sorts_by_degree_and_limits() -> None:
    """상위 Node API가 연결 수 내림차순 정렬과 limit을 적용하는지 검증한다."""
    with _graph_client(_FakeRankedGraphRepository()) as client:
        response = client.get(
            "/internal/v1/users/user-1/wiki/graph/top-nodes",
            params={"limit": 2},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["feature_id"] == "PWIKI-003"
    assert body["total_node_count"] == 3
    assert [item["document_id"] for item in body["items"]] == [
        "entity-a",
        "concept-b",
    ]
    assert [item["rank"] for item in body["items"]] == [1, 2]
    assert body["items"][0]["degree"] == 2
    assert "markdown" not in body["items"][0]


def test_wiki_top_nodes_api_requires_database_service(client: TestClient) -> None:
    """DB가 없는 Runtime은 상위 Node 조회에 SERVICE_NOT_READY를 반환한다."""
    response = client.get("/internal/v1/users/user-1/wiki/graph/top-nodes")

    assert response.status_code == 503
    assert response.json()["code"] == "SERVICE_NOT_READY"


def test_wiki_graph_page_contains_local_interactive_graph(client: TestClient) -> None:
    """시각화 페이지가 외부 CDN 없이 검색·필터·상세 Graph UI를 포함한다."""
    response = client.get("/wiki-graph?user_id=mock-clipping-user")

    assert response.status_code == 200
    assert "Report Builder Wiki Graph" in response.text
    assert 'id="api-token"' in response.text
    assert 'id="graph-search"' in response.text
    assert 'id="filter-entity"' in response.text
    assert 'id="detail-markdown"' in response.text
    assert "requestAnimationFrame(simulate)" in response.text
    assert "https://cdn" not in response.text


def test_wiki_graph_page_reuses_and_applies_persisted_bearer_token(
    client: TestClient,
) -> None:
    """Graph 화면이 저장 토큰과 Swagger 인증을 읽어 Authorization에 적용한다."""
    response = client.get("/wiki-graph?user_id=mock-clipping-user")

    assert response.status_code == 200
    assert '"report-builder-agent-api-token"' in response.text
    assert '"authorized"' in response.text
    assert "authorized?.InternalBearer" in response.text
    assert "headers.Authorization = `Bearer ${apiToken}`" in response.text
    assert "AGENT_INTERNAL_TOKEN 값을 위 인증란에 입력해주세요." in response.text


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
