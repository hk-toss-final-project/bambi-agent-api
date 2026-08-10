"""LLM Wiki Navigator API와 애플리케이션 서비스를 검증한다."""

from collections.abc import Sequence
from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import AppContainer
from app.main import create_app
from app.services.wiki_navigator import WikiNavigatorService
from shared.wiki_navigation_models import (
    WikiNavigationCandidate,
    WikiNavigationExcerpt,
    WikiNavigationPacket,
    WikiNavigationPage,
    WikiNavigationSource,
)
from tests.conftest import TEST_AUTHORIZATION_HEADER, TEST_INTERNAL_TOKEN


class _FakeNavigatorRepository:
    """API 계약용 결정적 Navigator Packet을 반환하는 저장소 대역."""

    def __init__(self) -> None:
        """마지막 호출 인자를 기록할 공간을 초기화한다."""
        self.calls: list[dict[str, object]] = []

    async def navigate_wiki(
        self,
        user_id: str,
        *,
        query: str,
        selected_document_version_ids: Sequence[str],
        wiki_version_id: str | None,
        candidate_limit: int,
        max_depth: int,
        max_pages: int,
        max_chunks: int,
        query_embedding: Sequence[float] | None,
    ) -> WikiNavigationPacket:
        """전달 인자를 기록하고 선택 여부에 따라 Page가 포함된 Packet을 반환한다."""
        self.calls.append(
            {
                "user_id": user_id,
                "query": query,
                "selected": tuple(selected_document_version_ids),
                "candidate_limit": candidate_limit,
                "query_embedding": tuple(query_embedding or ()),
            }
        )
        now = datetime(2026, 8, 10, 9, 30, tzinfo=UTC)
        candidate = WikiNavigationCandidate(
            document_id="doc-samsung",
            document_version_id="version-samsung",
            document_kind="entity",
            document_key="삼성전자",
            file_path="entities/삼성전자.md",
            title="삼성전자",
            aliases=("Samsung Electronics",),
            summary="반도체와 모바일 사업을 운영한다.",
            updated_at=now,
            exact_match=True,
            keyword_rank=1,
            rrf_score=0.1,
        )
        pages = ()
        sources = ()
        if selected_document_version_ids:
            pages = (
                WikiNavigationPage(
                    document_id=candidate.document_id,
                    document_version_id=candidate.document_version_id,
                    document_kind=candidate.document_kind,
                    document_key=candidate.document_key,
                    file_path=candidate.file_path,
                    title=candidate.title,
                    aliases=candidate.aliases,
                    summary=candidate.summary,
                    markdown="# 삼성전자",
                    version=3,
                    updated_at=now,
                    role="seed",
                    excerpts=(
                        WikiNavigationExcerpt(
                            chunk_id="chunk-1",
                            chunk_index=0,
                            content="최근 삼성전자 반도체에 관심을 보였다.",
                        ),
                    ),
                ),
            )
            sources = (
                WikiNavigationSource(
                    wiki_document_version_id="version-samsung",
                    source_document_id="source-1",
                    source_document_version_id="source-version-1",
                    source_type="web_clipping",
                    title="삼성전자 메모",
                    url="https://example.com/samsung",
                    relation_type="derived_from",
                    saved_at=now,
                    saved_at_source="event_occurred_at",
                    stored_at=now,
                    published_at=None,
                    clipped_on=date(2026, 8, 10),
                ),
            )
        return WikiNavigationPacket(
            query=query,
            wiki_version_id=wiki_version_id,
            candidates=(candidate,),
            pages=pages,
            relations=(),
            sources=sources,
            trace=(),
        )


def _navigation_client(
    repository: _FakeNavigatorRepository | None = None,
) -> tuple[TestClient, _FakeNavigatorRepository]:
    """가짜 Navigator가 연결된 인증 TestClient를 만든다."""
    resolved = repository or _FakeNavigatorRepository()
    settings = Settings(
        app_name="Wiki Navigator Test",
        environment="test",
        internal_api_token=TEST_INTERNAL_TOKEN,
    )
    service = WikiNavigatorService(
        resolved,
        embedding_function=lambda queries: {queries[0]: [0.1, 0.2]},
    )
    container = AppContainer(settings=settings, wiki_navigator_service=service)
    client = TestClient(create_app(settings, container))
    client.headers.update(TEST_AUTHORIZATION_HEADER)
    return client, resolved


def test_navigate_api_returns_thirty_candidates_before_selection() -> None:
    """선택 전 요청은 기본 후보 상한 30을 전달하고 Page 없는 Packet을 반환한다."""
    client, repository = _navigation_client()

    with client:
        response = client.post(
            "/internal/v1/users/user-1/wiki/navigate",
            json={"query": "삼성전자 관심"},
        )

    assert response.status_code == 200
    assert response.json()["feature_id"] == "WNAV-006"
    assert response.json()["candidates"][0]["title"] == "삼성전자"
    assert response.json()["pages"] == []
    assert repository.calls[0]["candidate_limit"] == 30
    assert repository.calls[0]["query_embedding"] == (0.1, 0.2)


def test_navigate_api_returns_selected_page_and_saved_at() -> None:
    """Consumer가 Seed를 고르면 Page와 원본 저장 시각을 함께 반환한다."""
    client, repository = _navigation_client()

    with client:
        response = client.post(
            "/internal/v1/users/user-1/wiki/navigate",
            json={
                "query": "최근 삼성전자 관심",
                "selected_document_version_ids": ["version-samsung"],
                "max_depth": 2,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["pages"][0]["document_version_id"] == "version-samsung"
    assert body["sources"][0]["saved_at"] == "2026-08-10T09:30:00Z"
    assert body["sources"][0]["saved_at_source"] == "event_occurred_at"
    assert repository.calls[0]["selected"] == ("version-samsung",)
    assert "answer" not in body


def test_navigate_api_rejects_more_than_thirty_candidates() -> None:
    """API 스키마가 합의된 후보 상한 30을 넘는 요청을 거부한다."""
    client, _ = _navigation_client()

    with client:
        response = client.post(
            "/internal/v1/users/user-1/wiki/navigate",
            json={"query": "삼성전자", "candidate_limit": 31},
        )

    assert response.status_code == 422


def test_navigate_api_requires_database_service(client: TestClient) -> None:
    """DB 없는 Runtime은 빈 성공 대신 SERVICE_NOT_READY를 반환한다."""
    response = client.post(
        "/internal/v1/users/user-1/wiki/navigate",
        json={"query": "삼성전자"},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "SERVICE_NOT_READY"
