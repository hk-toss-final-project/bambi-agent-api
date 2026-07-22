"""관심 키워드 기반 최신 정보 수집 애플리케이션 서비스를 검증한다."""

import asyncio
from dataclasses import asdict
from datetime import UTC, datetime

from app.config import Settings
from app.schemas.interests import InterestProfileResponse
from app.schemas.development import LatestNewsWorkerRunRequest
from app.schemas.latest_information import LatestInformationSearchRequest
from app.services.latest_information import LatestInformationService
from infrastructure.sources.connectors.api import LatestArticle, LatestProviderError


class _FakeInterests:
    """활성 관심 키워드 두 개를 반환하는 서비스 대역."""

    async def get_active(self, user_id: str) -> InterestProfileResponse:
        """최신 검색에 사용할 결정적인 관심 Profile을 반환한다."""
        return InterestProfileResponse.model_validate(
            {
                "profile_id": "profile-1",
                "user_id": user_id,
                "wiki_version_id": "wiki-1",
                "version": 1,
                "status": "active",
                "calculated_at": datetime.now(UTC),
                "interests": [
                    {
                        "interest_id": "interest-1",
                        "topic": "AI Agent",
                        "score": 1,
                        "confidence": 0.9,
                        "document_ids": ["doc-1"],
                        "evidence": {},
                    },
                    {
                        "interest_id": "interest-2",
                        "topic": "PostgreSQL",
                        "score": 0.8,
                        "confidence": 0.8,
                        "document_ids": ["doc-2"],
                        "evidence": {},
                    },
                ],
            }
        )


class _FakeProvider:
    """한 건의 최신 기사를 반환하는 Provider 대역."""

    name = "gdelt"

    async def search(
        self, *, query: str, limit: int, language: str | None
    ) -> list[LatestArticle]:
        """검색 Query를 설명에 넣은 기사 한 건을 반환한다."""
        return [
            LatestArticle(
                provider="gdelt",
                title="최신 소식",
                url="https://example.com/latest",
                description=query,
                published_at=datetime.now(UTC),
            )
        ]


class _FakeRepository:
    """저장된 최신 기사에 Global 문서 ID를 붙이는 저장소 대역."""

    async def save_latest_articles(
        self, *, provider: str, query: str, articles: list[LatestArticle]
    ) -> list[dict[str, object]]:
        """정규화 기사에 결정적인 문서 식별자를 추가한다."""
        article = articles[0]
        return [
            {
                **asdict(article),
                "document_id": "global-doc-1",
                "document_version_id": "global-version-1",
                "version": 1,
                "created": True,
            }
        ]


def test_latest_search_uses_active_interests_and_persists_results() -> None:
    """직접 키워드가 없으면 관심 Topic으로 검색하고 Global ID를 반환하는지 검증한다."""
    service = LatestInformationService(
        _FakeRepository(),  # type: ignore[arg-type]
        _FakeInterests(),  # type: ignore[arg-type]
        Settings(environment="test"),
        provider_factory=lambda _: _FakeProvider(),
    )

    response = asyncio.run(
        service.search(
            "user-1",
            LatestInformationSearchRequest(providers=["gdelt"]),
        )
    )

    assert response.keywords == ["AI Agent", "PostgreSQL"]
    assert response.query == "AI Agent PostgreSQL"
    assert response.items[0].document_id == "global-doc-1"


def test_latest_search_returns_provider_partial_failure() -> None:
    """Provider 준비 실패가 전체 요청 예외 대신 부분 실패로 반환되는지 검증한다."""

    def failing_factory(_: str) -> _FakeProvider:
        """Provider 미설정 오류를 발생시킨다."""
        raise LatestProviderError("naver", "provider_not_ready", "설정 필요")

    service = LatestInformationService(
        _FakeRepository(),  # type: ignore[arg-type]
        _FakeInterests(),  # type: ignore[arg-type]
        Settings(environment="test"),
        provider_factory=failing_factory,
    )

    response = asyncio.run(
        service.search(
            "user-1",
            LatestInformationSearchRequest(
                keywords=["AI"],
                providers=["naver"],
            ),
        )
    )

    assert response.items == []
    assert response.provider_failures[0].error_code == "provider_not_ready"


def test_run_news_worker_maps_collector_results() -> None:
    """수집 Worker 결과가 집계·저장 문서·부분 실패로 매핑되는지 검증한다."""
    captured: dict[str, object] = {}

    async def fake_collector(**kwargs: object) -> list[dict[str, object]]:
        """호출 인자를 기록하고 Provider별 수집 결과를 반환한다."""
        captured.update(kwargs)
        return [
            {
                "provider": "gdelt",
                "status": "completed",
                "query": "AI",
                "fetched_count": 3,
                "created_count": 1,
                "items": [
                    {
                        "provider": "gdelt",
                        "title": "최신 소식",
                        "url": "https://example.com/latest",
                        "document_id": "doc-1",
                        "document_version_id": "ver-1",
                        "content_status": "pending",
                        "published_at": None,
                        "source_name": "example.com",
                        "language": "ko",
                    }
                ],
            },
            {
                "provider": "naver",
                "status": "failed",
                "error_code": "provider_not_ready",
                "error_message": "설정 필요",
            },
        ]

    service = LatestInformationService(
        _FakeRepository(),  # type: ignore[arg-type]
        _FakeInterests(),  # type: ignore[arg-type]
        Settings(environment="test"),
        news_collector=fake_collector,
    )

    response = asyncio.run(
        service.run_news_worker(
            LatestNewsWorkerRunRequest(
                providers=["gdelt", "naver"],
                keywords=[" AI ", ""],
                limit_per_provider=5,
            )
        )
    )

    assert captured["keywords"] == ["AI"]
    assert captured["providers"] == ["gdelt", "naver"]
    assert response.status == "completed"
    assert response.collected_count == 3
    assert response.stored_count == 1
    assert response.items[0].document_id == "doc-1"
    assert response.items[0].description == ""
    assert response.items[0].created is True
    assert response.provider_failures[0].provider == "naver"
    assert response.provider_failures[0].error_code == "provider_not_ready"


def test_run_news_worker_requires_keywords() -> None:
    """키워드가 비면 수집 Worker가 ValueError를 발생시키는지 검증한다."""

    async def unused_collector(**_: object) -> list[dict[str, object]]:
        """호출되지 않아야 하는 수집 대역."""
        raise AssertionError("키워드가 없으면 Collector를 호출하지 않아야 한다.")

    service = LatestInformationService(
        _FakeRepository(),  # type: ignore[arg-type]
        _FakeInterests(),  # type: ignore[arg-type]
        Settings(environment="test"),
        news_collector=unused_collector,
    )

    try:
        asyncio.run(
            service.run_news_worker(
                LatestNewsWorkerRunRequest(providers=["gdelt"], keywords=["   "])
            )
        )
    except ValueError as error:
        assert "키워드" in str(error)
    else:  # pragma: no cover - 실패 경로 방어
        raise AssertionError("빈 키워드는 ValueError를 발생시켜야 한다.")
