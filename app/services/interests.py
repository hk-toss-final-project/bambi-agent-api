"""개인 Wiki 기반 관심 키워드 계산·조회 애플리케이션 서비스."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from fastapi import status

from agent.wiki_builder.api import InterestCandidate, extract_interest_candidates
from app.exceptions import AgentApiError, ErrorDetail
from app.schemas.interests import InterestProfileResponse


class InterestRepository(Protocol):
    """관심 키워드 계산 입력과 Profile 저장소 계약."""

    async def load_interest_documents(self, user_id: str) -> Mapping[str, object]:
        """활성 Wiki Build와 현재 Wiki 문서를 반환한다."""
        ...

    async def save_interest_profile(
        self,
        user_id: str,
        *,
        wiki_version_id: str,
        candidates: Sequence[InterestCandidate],
    ) -> Mapping[str, object]:
        """새 관심 Profile Version과 근거를 저장한다."""
        ...

    async def list_interests(self, user_id: str) -> Mapping[str, object] | None:
        """활성 관심 Profile을 반환한다."""
        ...


class InterestService:
    """활성 개인 Wiki에서 관심 키워드를 계산하고 조회한다."""

    def __init__(self, repository: InterestRepository) -> None:
        """관심 Profile Repository를 주입한다."""
        self._repository = repository

    async def rebuild(self, user_id: str, *, limit: int) -> InterestProfileResponse:
        """현재 Wiki 문서에서 관심 후보를 계산해 새 Profile로 활성화한다."""
        source = await self._repository.load_interest_documents(user_id)
        wiki_version_id = source.get("wiki_version_id")
        documents = source.get("documents")
        if not isinstance(wiki_version_id, str):
            raise AgentApiError(
                status.HTTP_409_CONFLICT,
                ErrorDetail(
                    code="ACTIVE_WIKI_REQUIRED",
                    message="관심 키워드를 계산할 활성 개인 Wiki가 필요합니다.",
                ),
            )
        document_rows = documents if isinstance(documents, list) else []
        candidates = extract_interest_candidates(document_rows, limit=limit)
        payload = await self._repository.save_interest_profile(
            user_id,
            wiki_version_id=wiki_version_id,
            candidates=candidates,
        )
        return InterestProfileResponse.model_validate(payload)

    async def get_active(self, user_id: str) -> InterestProfileResponse:
        """현재 활성 관심 Profile을 반환한다."""
        payload = await self._repository.list_interests(user_id)
        if payload is None:
            raise AgentApiError(
                status.HTTP_404_NOT_FOUND,
                ErrorDetail(
                    code="INTEREST_PROFILE_NOT_FOUND",
                    message="활성 관심 Profile을 찾을 수 없습니다.",
                ),
            )
        return InterestProfileResponse.model_validate(payload)
