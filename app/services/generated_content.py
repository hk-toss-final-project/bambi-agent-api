"""Bambi 생성 콘텐츠 후보 목록·상세 조회 애플리케이션 서비스."""

from typing import Mapping, Protocol

from fastapi import status

from app.exceptions import AgentApiError, ErrorDetail
from app.schemas.generated_content import (
    GeneratedContentDetailResponse,
    GeneratedContentListResponse,
)


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
    """BAMBI-018 저장 결과를 조회 API 모델로 제공한다."""

    def __init__(self, repository: GeneratedContentRepository) -> None:
        """생성 콘텐츠 Repository를 주입한다."""
        self._repository = repository

    async def list_contents(
        self, user_id: str, *, limit: int, offset: int
    ) -> GeneratedContentListResponse:
        """사용자 생성 후보 목록을 검증해 반환한다."""
        payload = await self._repository.list_generated_contents(
            user_id, limit=limit, offset=offset
        )
        return GeneratedContentListResponse.model_validate(payload)

    async def get_content(
        self, user_id: str, candidate_id: str
    ) -> GeneratedContentDetailResponse:
        """생성 후보 상세를 반환하고 다른 사용자 후보는 숨긴다."""
        payload = await self._repository.get_generated_content(user_id, candidate_id)
        if payload is None:
            raise AgentApiError(
                status.HTTP_404_NOT_FOUND,
                ErrorDetail(
                    code="GENERATED_CONTENT_NOT_FOUND",
                    message="생성 콘텐츠를 찾을 수 없습니다.",
                ),
            )
        return GeneratedContentDetailResponse.model_validate(payload)
