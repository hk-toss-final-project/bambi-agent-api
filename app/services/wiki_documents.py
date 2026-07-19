"""개인 Wiki 문서 목록·상세·Build 조회 애플리케이션 서비스.

PostgreSQL Repository 결과를 API Schema로 검증하고 사용자에게 존재하지 않는
문서를 안전한 404 오류로 변환한다.
"""

from typing import Mapping, Protocol

from fastapi import status

from app.exceptions import AgentApiError, ErrorDetail
from app.schemas.wiki import (
    WikiBuildDetailResponse,
    WikiDocumentDetailResponse,
    WikiDocumentListResponse,
)


class WikiDocumentRepository(Protocol):
    """개인 Wiki 문서와 Build Snapshot 조회 저장소 계약."""

    async def list_documents(
        self,
        user_id: str,
        *,
        document_kind: str | None,
        limit: int,
        offset: int,
    ) -> Mapping[str, object]:
        """현재 Wiki 문서 목록과 전체 개수를 반환한다."""
        ...

    async def get_document(
        self, user_id: str, document_id: str
    ) -> Mapping[str, object] | None:
        """현재 Wiki 문서 Markdown과 출처·관계를 반환한다."""
        ...

    async def get_wiki_version(
        self, user_id: str, wiki_version_id: str
    ) -> Mapping[str, object] | None:
        """특정 Wiki Build Snapshot을 반환한다."""
        ...


class WikiDocumentService:
    """PWIKI-003·PWIKI-006 조회 응답을 조립한다."""

    def __init__(self, repository: WikiDocumentRepository) -> None:
        """개인 Wiki 문서 Repository를 주입한다."""
        self._repository = repository

    async def list_documents(
        self,
        user_id: str,
        *,
        document_kind: str | None,
        limit: int,
        offset: int,
    ) -> WikiDocumentListResponse:
        """사용자 Namespace의 현재 Wiki 문서 목록을 검증해 반환한다."""
        payload = await self._repository.list_documents(
            user_id,
            document_kind=document_kind,
            limit=limit,
            offset=offset,
        )
        return WikiDocumentListResponse.model_validate(payload)

    async def get_document(
        self, user_id: str, document_id: str
    ) -> WikiDocumentDetailResponse:
        """현재 Wiki 문서 상세를 반환하고 다른 사용자 문서는 숨긴다."""
        payload = await self._repository.get_document(user_id, document_id)
        if payload is None:
            raise AgentApiError(
                status.HTTP_404_NOT_FOUND,
                ErrorDetail(
                    code="WIKI_DOCUMENT_NOT_FOUND",
                    message="개인 Wiki 문서를 찾을 수 없습니다.",
                ),
            )
        return WikiDocumentDetailResponse.model_validate(payload)

    async def get_wiki_version(
        self, user_id: str, wiki_version_id: str
    ) -> WikiBuildDetailResponse:
        """Wiki Build Snapshot을 반환하고 다른 사용자 Build는 숨긴다."""
        payload = await self._repository.get_wiki_version(user_id, wiki_version_id)
        if payload is None:
            raise AgentApiError(
                status.HTTP_404_NOT_FOUND,
                ErrorDetail(
                    code="WIKI_VERSION_NOT_FOUND",
                    message="개인 Wiki Build를 찾을 수 없습니다.",
                ),
            )
        return WikiBuildDetailResponse.model_validate(payload)
