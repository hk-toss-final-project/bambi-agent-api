"""아침 브리핑 주제 선정 애플리케이션 서비스.

Wiki 후보와 원자재를 Repository에서 읽고, 맥락을 조립해 선정자에게 넘긴다.
LLM 호출은 DB Transaction 밖에서 수행한다.
"""

from __future__ import annotations

import logging
from asyncio import to_thread
from collections.abc import Sequence
from typing import Protocol

from agent.report_builder.api import (
    DEFAULT_BRIEFING_CANDIDATE_LIMIT,
    DEFAULT_BRIEFING_TOPIC_COUNT,
    CandidateMaterial,
    build_interest_context,
    select_briefing_topics,
)
from app.schemas.briefing_topics import BriefingTopicsResponse

logger = logging.getLogger("app.services.briefing_topics")


class BriefingCandidateRepository(Protocol):
    """아침 브리핑 후보 원자재를 읽는 Repository 계약."""

    async def load_briefing_candidates(
        self, user_id: str, *, limit: int
    ) -> Sequence[CandidateMaterial]:
        """Wiki Node 후보와 각 후보의 요약·출처·저장 시각을 읽는다."""
        ...


class BriefingTopicsService:
    """개인 Wiki 맥락을 읽어 아침 브리핑 주제를 고른다."""

    def __init__(self, repository: BriefingCandidateRepository) -> None:
        """후보 조회 Repository를 주입한다."""
        self._repository = repository

    async def get_topics(
        self,
        user_id: str,
        *,
        limit: int = DEFAULT_BRIEFING_TOPIC_COUNT,
        candidate_limit: int = DEFAULT_BRIEFING_CANDIDATE_LIMIT,
    ) -> BriefingTopicsResponse:
        """맥락을 읽고 아침에 받아볼 주제를 고른다.

        **빈 목록을 정상 응답으로 돌려준다.** Wiki가 없는 신규 사용자가 여기에
        해당하며, 계약상 Service는 `topics`가 비면 아침 요청을 보내지 않고
        등록 관심사 폴백으로 넘어간다.

        Args:
            user_id: 조회 대상 사용자 ID
            limit: 고를 주제 수
            candidate_limit: 선정자에게 넘길 후보 수

        Returns:
            고른 주제와 사유, 검토한 후보 수
        """
        materials = await self._repository.load_briefing_candidates(
            user_id, limit=candidate_limit
        )
        context = build_interest_context(materials)
        # 선정자는 동기 함수이고 LLM을 부른다. 이벤트 루프를 막지 않도록 분리한다.
        selection = await to_thread(select_briefing_topics, context, limit=limit)
        logger.info(
            "아침 주제 선정 완료: user=%s 후보=%d 결과=%s",
            user_id,
            len(context.candidates),
            ", ".join(selection.topics) or "(없음)",
        )
        return BriefingTopicsResponse(
            user_id=user_id,
            topics=list(selection.topics),
            reason=selection.reason,
            candidate_count=len(context.candidates),
        )
