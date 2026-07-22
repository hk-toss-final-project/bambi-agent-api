"""Agent Job 생성 명세와 조회 기능 및 미구현 Lifecycle Scaffold."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from domain.jobs.features.idempotency import job_010
from shared.contracts import FeatureRequest, FeatureResult


@dataclass(frozen=True, slots=True)
class AgentJobCreation:
    """DB에 저장할 Agent Job의 정규화된 생성 값."""

    feature_id: str
    job_type: str
    user_id: str
    idempotency_key: str
    payload: dict[str, object]
    request_id: str | None


class JobReader[RecordT](Protocol):
    """Agent Job 단건 조회에 필요한 저장소 경계."""

    async def get_job(self, job_id: str) -> RecordT | None:
        """식별자에 해당하는 Agent Job을 반환한다."""
        ...


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def job_001(
    *,
    feature_id: str,
    job_type: str,
    user_id: str,
    idempotency_parts: list[str],
    payload: Mapping[str, object],
    request_id: str | None,
) -> AgentJobCreation:
    """[JOB-001] Agent Job 생성.

    비동기 Agent 작업을 생성하고 Queue에 등록한다.
    """
    if not feature_id or not job_type or not user_id:
        raise ValueError("JOB-001에 feature_id, job_type, user_id가 필요합니다.")
    return AgentJobCreation(
        feature_id=feature_id,
        job_type=job_type,
        user_id=user_id,
        idempotency_key=await job_010(idempotency_parts),
        payload=dict(payload),
        request_id=request_id,
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def job_002[RecordT](reader: JobReader[RecordT], job_id: str) -> RecordT | None:
    """[JOB-002] Agent Job 조회.

    작업의 상태와 진행률을 조회한다.
    """
    if not job_id:
        raise ValueError("JOB-002에 job_id가 필요합니다.")
    return await reader.get_job(job_id)


async def job_003(request: FeatureRequest) -> FeatureResult:
    """[JOB-003] Agent Job 목록 조회.

    유형, 사용자, 상태별 작업 목록을 조회한다.
    """
    raise NotImplementedError("[JOB-003] 기능 구현이 필요합니다.")


async def job_004(request: FeatureRequest) -> FeatureResult:
    """[JOB-004] Agent Job 취소.

    취소 가능한 작업을 중단한다.
    """
    raise NotImplementedError("[JOB-004] 기능 구현이 필요합니다.")
