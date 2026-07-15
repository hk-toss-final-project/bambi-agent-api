"""개인 Wiki Graph 조회 애플리케이션 서비스.

FastAPI 요청 Context를 PWIKI-003 기능 계약으로 변환하고 Graph 응답
스키마를 검증해 라우터가 DB 구현 세부사항을 알지 않도록 한다.
"""

from typing import Mapping, Protocol

from app.schemas.wiki import WikiGraphResponse
from domain.personal_wiki.documents.api import pwiki_003
from shared.contracts import FeatureRequest


class WikiGraphRepository(Protocol):
    """개인 Wiki Graph를 조회하는 Repository 계약."""

    async def get_graph(self, user_id: str) -> Mapping[str, object]:
        """사용자 Namespace의 현재 Graph를 반환한다."""
        ...


class WikiGraphService:
    """PWIKI-003을 호출해 검증된 Graph API 응답을 만드는 서비스."""

    def __init__(self, repository: WikiGraphRepository) -> None:
        """개인 Wiki Graph Repository를 주입한다."""
        self._repository = repository

    async def get_graph(self, user_id: str, request_id: str) -> WikiGraphResponse:
        """사용자 Graph를 조회하고 Pydantic 응답으로 검증한다."""
        result = await pwiki_003(
            FeatureRequest(
                request_id=request_id,
                actor_id="service-api",
                user_id=user_id,
                payload={"reader": self._repository},
            )
        )
        return WikiGraphResponse.model_validate(
            {"feature_id": result.feature_id, **dict(result.data)}
        )
