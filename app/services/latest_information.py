"""관심 키워드로 최신 외부 자료를 수집·저장하는 애플리케이션 서비스."""

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol
from uuid import uuid4

from app.config import Settings
from app.schemas.development import (
    LatestNewsWorkerRunRequest,
    LatestNewsWorkerRunResponse,
)
from app.schemas.latest_information import (
    LatestInformationSearchRequest,
    LatestInformationSearchResponse,
)
from app.services.interests import InterestService
from infrastructure.sources.connectors.api import (
    GdeltNewsProvider,
    GoogleNewsRssProvider,
    LatestArticle,
    LatestInformationProvider,
    LatestProviderError,
    NaverNewsProvider,
    NewsApiProvider,
    col_001,
    col_002,
    col_003,
    col_004,
)
from infrastructure.sources.processing.api import gsp_004, gsp_006, gsp_015


class LatestInformationRepository(Protocol):
    """정규화된 최신 문서를 Global Namespace에 저장하는 계약."""

    async def save_latest_articles(
        self,
        *,
        provider: str,
        query: str,
        articles: Sequence[LatestArticle],
    ) -> list[dict[str, object]]:
        """최신 문서 Version과 Chunk를 멱등 저장한다."""
        ...


type ProviderFactory = Callable[[str], LatestInformationProvider]

# 배치 뉴스 수집 Worker를 실행해 Provider별 결과 목록을 반환하는 호출 계약.
type NewsCollector = Callable[..., Awaitable[list[dict[str, object]]]]


class LatestInformationService:
    """직접 또는 사용자 관심 키워드로 최신 Global 문서를 수집한다."""

    def __init__(
        self,
        repository: LatestInformationRepository,
        interests: InterestService,
        settings: Settings,
        *,
        provider_factory: ProviderFactory | None = None,
        news_collector: NewsCollector | None = None,
    ) -> None:
        """Global 저장소, 관심 서비스와 Provider 설정을 주입한다."""
        self._repository = repository
        self._interests = interests
        self._settings = settings
        self._provider_factory = provider_factory or self._build_provider
        self._news_collector = news_collector

    def _build_provider(self, name: str) -> LatestInformationProvider:
        """환경 설정의 Secret으로 요청된 최신 정보 Provider를 구성한다."""
        if name == "naver":
            if not self._settings.naver_client_id or not self._settings.naver_client_secret:
                raise LatestProviderError(
                    name, "provider_not_ready", "NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET이 필요합니다."
                )
            return NaverNewsProvider(
                self._settings.naver_client_id,
                self._settings.naver_client_secret.get_secret_value(),
            )
        if name == "newsapi":
            if not self._settings.news_api_key:
                raise LatestProviderError(
                    name, "provider_not_ready", "NEWS_API_KEY가 필요합니다."
                )
            return NewsApiProvider(self._settings.news_api_key.get_secret_value())
        if name == "gdelt":
            return GdeltNewsProvider(
                self._settings.gdelt_base_url or "https://api.gdeltproject.org"
            )
        if name == "google_news":
            return GoogleNewsRssProvider()
        raise LatestProviderError(name, "unsupported_provider", "지원하지 않는 Provider입니다.")

    async def search(
        self, user_id: str, payload: LatestInformationSearchRequest
    ) -> LatestInformationSearchResponse:
        """Provider별 최신 정보를 수집해 Global 문서로 저장하고 부분 실패를 반환한다."""
        keywords = [keyword.strip() for keyword in payload.keywords]
        if not keywords:
            profile = await self._interests.get_active(user_id)
            keywords = [interest.topic for interest in profile.interests[:5]]
        query = " ".join(keywords)
        items: list[dict[str, object]] = []
        failures: list[dict[str, object]] = []
        for provider_name in payload.providers:
            try:
                provider = self._provider_factory(provider_name)
                connector = {
                    "naver": col_002,
                    "gdelt": col_003,
                    "newsapi": col_004,
                    "google_news": col_001,
                }.get(provider_name)
                if connector is None:
                    raise LatestProviderError(
                        provider_name,
                        "unsupported_provider",
                        "지원하지 않는 Provider입니다.",
                    )
                collected = await connector(
                    provider,
                    query=query,
                    limit=payload.limit_per_provider,
                    language=payload.language,
                )
                normalized = await gsp_004(collected)
                deduplicated = await gsp_006(normalized)
                await gsp_015("global")
                saved = await self._repository.save_latest_articles(
                    provider=provider_name,
                    query=query,
                    articles=deduplicated,
                )
                items.extend(saved)
            except LatestProviderError as error:
                failures.append(
                    {
                        "provider": provider_name,
                        "error_code": error.error_code,
                        "message": str(error),
                    }
                )
        return LatestInformationSearchResponse.model_validate(
            {
                "user_id": user_id,
                "query": query,
                "keywords": keywords,
                "items": items,
                "provider_failures": failures,
            }
        )

    async def run_news_worker(
        self, payload: LatestNewsWorkerRunRequest
    ) -> LatestNewsWorkerRunResponse:
        """키워드로 최신 뉴스 수집 Worker를 실행해 Global 문서로 저장한다.

        요청 키워드로 GDELT·Naver Provider를 호출해 기사 URL을 Global
        Namespace에 stub 저장하고, Provider별 수집·저장 집계와 부분 실패를
        하나의 Worker 실행 결과로 합쳐 반환한다. 본문은 이후 본문 수집
        Worker(global_content_fetcher)가 채운다.

        Args:
            payload: 수집 Provider·키워드·Provider별 최대 개수 요청

        Returns:
            수집·저장 집계와 저장 문서, Provider별 실패를 담은 실행 결과
        """
        keywords = [keyword.strip() for keyword in payload.keywords if keyword.strip()]
        if not keywords:
            raise ValueError("최신 뉴스 수집에는 키워드가 하나 이상 필요합니다.")
        collector = self._news_collector
        if collector is None:
            from workers.api import worker_001

            collector = worker_001
        naver_secret = (
            self._settings.naver_client_secret.get_secret_value()
            if self._settings.naver_client_secret
            else None
        )
        results = await collector(
            database_url=self._settings.agent_database_url,
            keywords=keywords,
            providers=list(payload.providers),
            limit_per_provider=payload.limit_per_provider,
            language=None,
            naver_client_id=self._settings.naver_client_id,
            naver_client_secret=naver_secret,
            gdelt_base_url=self._settings.gdelt_base_url,
        )
        collected_count = 0
        stored_count = 0
        items: list[dict[str, object]] = []
        failures: list[dict[str, object]] = []
        succeeded = False
        for result in results:
            if result.get("status") == "completed":
                succeeded = True
                collected_count += int(result.get("fetched_count", 0))
                stored_count += int(result.get("created_count", 0))
                for saved in result.get("items", []):
                    items.append(
                        {
                            "provider": saved["provider"],
                            "title": saved["title"],
                            "url": saved["url"],
                            "description": saved.get("description") or "",
                            "published_at": saved.get("published_at"),
                            "source_name": saved.get("source_name"),
                            "language": saved.get("language"),
                            "document_id": saved["document_id"],
                            "document_version_id": saved["document_version_id"],
                            "version": 1,
                            "created": True,
                        }
                    )
            else:
                failures.append(
                    {
                        "provider": result["provider"],
                        "error_code": result.get("error_code", "provider_failed"),
                        "message": str(result.get("error_message", "")),
                    }
                )
        return LatestNewsWorkerRunResponse.model_validate(
            {
                "run_id": str(uuid4()),
                "status": "completed" if succeeded else "failed",
                "keywords": keywords,
                "collected_count": collected_count,
                "stored_count": stored_count,
                "items": items,
                "provider_failures": failures,
            }
        )
