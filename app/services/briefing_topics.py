"""아침 브리핑 주제 선정 애플리케이션 서비스.

Wiki 후보와 원자재를 Repository에서 읽고, 맥락을 조립해 선정자에게 넘긴다.
LLM 호출은 DB Transaction 밖에서 수행한다.
"""

from __future__ import annotations

import hashlib
import logging
from asyncio import to_thread
from collections.abc import Sequence
from dataclasses import asdict
from datetime import date
from typing import Any, Mapping, Protocol

from agent.report_builder.api import (
    DEFAULT_BRIEFING_CANDIDATE_LIMIT,
    DEFAULT_BRIEFING_TOPIC_COUNT,
    CandidateMaterial,
    ReportContextDocument,
    build_interest_context,
    select_briefing_topics,
)
from app.schemas.briefing_topics import (
    BriefingPreparationStatus,
    BriefingPreparationRequest,
    BriefingTopicsResponse,
)
from app.schemas.mvp import AcceptedJobResponse, JobStatus
from app.services.agent_jobs import AgentJobRepository
from infrastructure.persistence.api import StoredBriefingTopicSnapshot

logger = logging.getLogger("app.services.briefing_topics")


def _candidate_digest(materials: Sequence[CandidateMaterial]) -> str:
    """선정 입력이 된 후보 목록의 지문을 만든다.

    같은 후보면 같은 답이 나오므로, 이 값이 재사용 가능 여부를 정한다. 노드
    이름과 요약까지 넣는다 — 이름이 같아도 요약이 바뀌면 선정자가 다르게
    판단할 수 있다. 출처는 넣지 않는다. 저장 시각까지 섞으면 내용이 그대로인데
    지문만 달라져 재사용이 사실상 안 된다.

    Args:
        materials: Repository가 돌려준 후보 원자재

    Returns:
        SHA-256 16진 문자열
    """
    digest = hashlib.sha256()
    for material in materials:
        digest.update(str(getattr(material, "node", "")).encode("utf-8"))
        digest.update(b"\x1f")
        digest.update(str(getattr(material, "summary", "")).encode("utf-8"))
        digest.update(b"\x1e")
    return digest.hexdigest()


class BriefingCandidateRepository(Protocol):
    """아침 브리핑 후보 원자재를 읽는 Repository 계약."""

    async def load_briefing_candidates(
        self, user_id: str, *, limit: int
    ) -> Sequence[CandidateMaterial]:
        """Wiki Node 후보와 각 후보의 요약·출처·저장 시각을 읽는다."""
        ...

    async def load_briefing_topic_snapshot(
        self, user_id: str, *, briefing_date: date
    ) -> StoredBriefingTopicSnapshot | None:
        """사용자·날짜별로 준비된 브리핑 Snapshot을 조회한다."""
        ...

    async def save_briefing_topic_snapshot(
        self,
        user_id: str,
        *,
        briefing_date: date,
        topics: Sequence[str],
        reason: str,
        candidate_count: int,
        contexts_by_topic: Mapping[str, Sequence[Mapping[str, object]]],
        prepared_by_job_id: str,
    ) -> StoredBriefingTopicSnapshot:
        """선정 주제와 사전 수집 근거를 날짜별 Snapshot으로 저장한다."""
        ...


class BriefingTopicsService:
    """개인 Wiki 맥락을 읽어 아침 브리핑 주제를 고른다."""

    def __init__(
        self,
        repository: BriefingCandidateRepository,
        agent_jobs: AgentJobRepository | None = None,
    ) -> None:
        """후보 조회 Repository를 주입한다."""
        self._repository = repository
        self._agent_jobs = agent_jobs

    async def get_topics(
        self,
        user_id: str,
        *,
        briefing_date: date,
        limit: int = DEFAULT_BRIEFING_TOPIC_COUNT,
    ) -> BriefingTopicsResponse:
        """준비 Worker가 저장한 날짜별 주제를 LLM 호출 없이 조회한다.

        Snapshot 유무를 `preparation_status`로 구분한다. `READY`이면서 빈 목록이면
        Wiki가 없거나 선정할 주제가 없는 정상 완료 상태이고, `NOT_PREPARED`이면
        호출자가 준비 Job을 연결해야 한다.

        Args:
            user_id: 조회 대상 사용자 ID
            limit: 고를 주제 수
        Returns:
            준비된 주제와 사유. Snapshot이 없으면 NOT_PREPARED
        """
        snapshot = await self._repository.load_briefing_topic_snapshot(
            user_id, briefing_date=briefing_date
        )
        if snapshot is None:
            return BriefingTopicsResponse(
                user_id=user_id,
                preparation_status=BriefingPreparationStatus.NOT_PREPARED,
            )
        return BriefingTopicsResponse(
            user_id=user_id,
            preparation_status=BriefingPreparationStatus.READY,
            topics=list(snapshot.topics[:limit]),
            reason=snapshot.reason,
            candidate_count=snapshot.candidate_count,
        )

    async def get_preparation_snapshot(
        self,
        user_id: str,
        *,
        briefing_date: date,
    ) -> StoredBriefingTopicSnapshot | None:
        """Worker의 멱등 재실행을 위해 날짜별 준비 Snapshot을 조회한다."""
        return await self._repository.load_briefing_topic_snapshot(
            user_id,
            briefing_date=briefing_date,
        )

    async def select_topics(
        self,
        user_id: str,
        *,
        limit: int = DEFAULT_BRIEFING_TOPIC_COUNT,
        candidate_limit: int = DEFAULT_BRIEFING_CANDIDATE_LIMIT,
    ) -> BriefingTopicsResponse:
        """준비 Worker에서만 Wiki 맥락을 읽고 브리핑 주제를 새로 선정한다."""
        materials = await self._repository.load_briefing_candidates(
            user_id, limit=candidate_limit
        )
        digest = _candidate_digest(materials)
        stored = await self._load_stored(user_id, digest=digest, topic_limit=limit)
        if stored is not None:
            logger.info(
                "아침 주제 재사용: user=%s 결과=%s",
                user_id,
                ", ".join(stored.topics) or "(없음)",
            )
            return BriefingTopicsResponse(
                user_id=user_id,
                topics=list(stored.topics),
                reason=stored.reason,
                candidate_count=stored.candidate_count,
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
        await self._save_selection(
            user_id,
            digest=digest,
            topics=list(selection.topics),
            reason=selection.reason,
            candidate_count=len(context.candidates),
            topic_limit=limit,
        )
        return BriefingTopicsResponse(
            user_id=user_id,
            topics=list(selection.topics),
            reason=selection.reason,
            candidate_count=len(context.candidates),
        )

    async def _load_stored(
        self, user_id: str, *, digest: str, topic_limit: int
    ) -> Any | None:
        """저장된 선정 결과를 읽되, 실패하면 새로 뽑는 쪽으로 넘긴다.

        캐시는 편의 장치라 여기서 예외를 올리면 안 된다. Repository가 저장을
        지원하지 않거나(테스트 대역) 조회가 실패해도 07:00 선정 자체는 돌아야
        한다.
        """
        loader = getattr(self._repository, "load_topic_selection", None)
        if loader is None:
            return None
        try:
            return await loader(
                user_id, candidate_digest=digest, topic_limit=topic_limit
            )
        except Exception:  # noqa: BLE001 - 캐시 실패로 선정을 막지 않는다
            logger.warning("아침 주제 캐시 조회 실패, 새로 고른다: user=%s", user_id)
            return None

    async def _save_selection(
        self,
        user_id: str,
        *,
        digest: str,
        topics: list[str],
        reason: str,
        candidate_count: int,
        topic_limit: int,
    ) -> None:
        """이번 선정 결과를 저장하되, 실패해도 응답은 그대로 내보낸다."""
        saver = getattr(self._repository, "save_topic_selection", None)
        if saver is None:
            return
        try:
            await saver(
                user_id,
                candidate_digest=digest,
                topics=topics,
                reason=reason,
                candidate_count=candidate_count,
                topic_limit=topic_limit,
            )
        except Exception:  # noqa: BLE001 - 저장 실패가 응답을 막지 않는다
            logger.warning("아침 주제 캐시 저장 실패: user=%s", user_id)

    async def enqueue_preparation(
        self,
        user_id: str,
        payload: BriefingPreparationRequest,
        *,
        request_id: str,
    ) -> AcceptedJobResponse:
        """사용자·날짜별 브리핑 준비 Job을 Agent Queue에 멱등 등록한다."""
        if self._agent_jobs is None:
            raise RuntimeError("브리핑 준비 Job 저장소가 구성되지 않았습니다.")
        job = await self._agent_jobs.submit_briefing_preparation(
            user_id=user_id,
            briefing_date=payload.briefing_date,
            idempotency_key=payload.idempotency_key,
            limit=payload.limit,
            request_id=request_id,
        )
        return AcceptedJobResponse(
            job_id=job.job_id,
            feature_id=job.feature_id,
            status=JobStatus(job.status),
            request_id=job.request_id,
            created_at=job.created_at,
        )

    async def save_preparation(
        self,
        user_id: str,
        *,
        briefing_date: date,
        selection: BriefingTopicsResponse,
        contexts_by_topic: Mapping[str, Sequence[ReportContextDocument]],
        prepared_by_job_id: str,
    ) -> StoredBriefingTopicSnapshot:
        """Worker가 고른 주제와 Context 문서를 JSON Snapshot으로 저장한다."""
        serialized = {
            topic: [asdict(context) for context in contexts]
            for topic, contexts in contexts_by_topic.items()
        }
        return await self._repository.save_briefing_topic_snapshot(
            user_id,
            briefing_date=briefing_date,
            topics=selection.topics,
            reason=selection.reason,
            candidate_count=selection.candidate_count,
            contexts_by_topic=serialized,
            prepared_by_job_id=prepared_by_job_id,
        )
