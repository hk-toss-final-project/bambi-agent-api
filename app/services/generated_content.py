"""Report Builder 생성 콘텐츠 후보 목록·상세 조회 애플리케이션 서비스."""

from typing import Mapping, Protocol

from fastapi import status

from app.exceptions import AgentApiError, ErrorDetail
from app.schemas.generated_content import (
    GeneratedContentDetailResponse,
    GeneratedContentListResponse,
)
from agent.report_builder.api import report_018
from shared.contracts import FeatureRequest


class GeneratedContentRepository(Protocol):
    """사용자별 생성 후보와 Citation 조회 저장소 계약."""

    async def list_generated_contents(
        self, user_id: str, *, limit: int, offset: int
    ) -> Mapping[str, object]:
        """사용자의 생성 후보 목록과 전체 개수를 반환한다."""
        ...

    async def get_generated_content(
        self, user_id: str, candidate_id: str
    ) -> Mapping[str, object] | None:
        """생성 후보 상세와 Citation을 반환한다."""
        ...


class GeneratedContentService:
    """REPORT-018 저장 결과를 조회 API 모델로 제공한다."""

    def __init__(self, repository: GeneratedContentRepository) -> None:
        """생성 콘텐츠 Repository를 주입한다."""
        self._repository = repository

    async def list_contents(
        self, user_id: str, *, limit: int, offset: int
    ) -> GeneratedContentListResponse:
        """사용자 생성 후보 목록을 검증해 반환한다."""
        result = await report_018(
            FeatureRequest(
                request_id=f"generated-contents:list:{user_id}",
                actor_id="generated-content-service",
                user_id=user_id,
                payload={
                    "implementation": lambda: self._repository.list_generated_contents(
                        user_id, limit=limit, offset=offset
                    )
                },
            )
        )
        return GeneratedContentListResponse.model_validate(result.data)

    async def get_content(
        self, user_id: str, candidate_id: str
    ) -> GeneratedContentDetailResponse:
        """생성 후보 상세를 반환하고 다른 사용자 후보는 숨긴다."""
        result = await report_018(
            FeatureRequest(
                request_id=f"generated-contents:detail:{candidate_id}",
                actor_id="generated-content-service",
                user_id=user_id,
                payload={
                    "implementation": lambda: self._repository.get_generated_content(
                        user_id, candidate_id
                    )
                },
            )
        )
        if result.data.get("result") is None and set(result.data) == {"result"}:
            raise AgentApiError(
                status.HTTP_404_NOT_FOUND,
                ErrorDetail(
                    code="GENERATED_CONTENT_NOT_FOUND",
                    message="생성 콘텐츠를 찾을 수 없습니다.",
                ),
            )
        return GeneratedContentDetailResponse.model_validate(result.data)
