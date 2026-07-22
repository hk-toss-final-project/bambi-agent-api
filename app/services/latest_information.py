"""관심 키워드로 최신 외부 자료를 수집·저장하는 애플리케이션 서비스."""

from collections.abc import Callable, Sequence
from typing import Protocol

from app.config import Settings
from app.schemas.latest_information import (
    LatestInformationSearchRequest,
    LatestInformationSearchResponse,
)
from app.services.interests import InterestService
from infrastructure.sources.connectors.api import (
    GdeltNewsProvider,
    LatestArticle,
    LatestInformationProvider,
    LatestProviderError,
    NaverNewsProvider,
    NewsApiProvider,
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


class LatestInformationService:
    """직접 또는 사용자 관심 키워드로 최신 Global 문서를 수집한다."""

    def __init__(
        self,
        repository: LatestInformationRepository,
        interests: InterestService,
        settings: Settings,
        *,
        provider_factory: ProviderFactory | None = None,
    ) -> None:
        """Global 저장소, 관심 서비스와 Provider 설정을 주입한다."""
        self._repository = repository
        self._interests = interests
        self._settings = settings
        self._provider_factory = provider_factory or self._build_provider

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
