"""Service Worker가 호출하는 발행 Snapshot과 ACK 내부 라우터."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.dependencies import get_mvp_service
from app.schemas.mvp import (
    PublishAckRequest,
    PublishAckResponse,
    PublishSnapshotResponse,
)
from app.services.mvp import AgentApiMvpService

router = APIRouter(tags=["service-worker"])


@router.get(
    "/publish-snapshots/{content_id}",
    response_model=PublishSnapshotResponse,
    operation_id="sw_004",
)
async def get_publish_snapshot(
    content_id: Annotated[str, Path(min_length=1, max_length=128)],
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> PublishSnapshotResponse:
    """[SW-004] service-db 저장에 사용할 최신 Publish Snapshot을 반환한다."""
    return await service.get_publish_snapshot(content_id)


@router.post(
    "/publish-snapshots/{content_id}/ack",
    response_model=PublishAckResponse,
    operation_id="sw_009",
)
async def acknowledge_publish(
    content_id: Annotated[str, Path(min_length=1, max_length=128)],
    payload: PublishAckRequest,
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> PublishAckResponse:
    """[SW-009] Service Worker의 service-db 반영 결과를 Agent API에 기록한다."""
    return await service.acknowledge_publish(content_id, payload)
