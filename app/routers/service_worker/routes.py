"""Service Worker가 호출하는 발행 Snapshot과 ACK 내부 라우터."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.dependencies import get_publish_snapshot_service
from app.schemas.mvp import (
    PublishAckRequest,
    PublishAckResponse,
    PublishBatchAckRequest,
    PublishBatchAckResponse,
    PublishBatchClaimRequest,
    PublishBatchClaimResponse,
    PublishSnapshotResponse,
)
from app.routers.service_worker.api import sw_004, sw_009
from app.security.internal_auth.api import require_service_worker_access
from app.services.publish_snapshots import PublishSnapshotService

router = APIRouter(
    tags=["service-worker"],
    dependencies=[Depends(require_service_worker_access)],
)


@router.get(
    "/publish-snapshots/{content_id}",
    response_model=PublishSnapshotResponse,
    operation_id="sw_004",
    summary="최신 Publish Snapshot 조회",
)
async def get_publish_snapshot(
    content_id: Annotated[str, Path(min_length=1, max_length=128)],
    service: PublishSnapshotService = Depends(get_publish_snapshot_service),
) -> PublishSnapshotResponse:
    """[SW-004] service-db 저장에 사용할 최신 Publish Snapshot을 반환한다."""
    return await sw_004(service, content_id)


@router.post(
    "/publish-snapshot-batches/claim",
    response_model=PublishBatchClaimResponse,
    operation_id="sw_004_batch_claim",
    summary="Publish Snapshot Batch Claim",
    description=(
        "준비된 Snapshot을 생성 시각 순으로 점유하고 service-db 저장에 필요한 "
        "전체 Payload와 Lease를 반환합니다. 처리할 항목이 없으면 items는 빈 목록입니다."
    ),
)
async def claim_publish_snapshot_batch(
    payload: PublishBatchClaimRequest,
    service: PublishSnapshotService = Depends(get_publish_snapshot_service),
) -> PublishBatchClaimResponse:
    """[SW-004] 준비된 Publish Snapshot을 Lease와 함께 Batch Claim한다."""
    return await sw_004(service, payload)


@router.post(
    "/publish-snapshots/{content_id}/ack",
    response_model=PublishAckResponse,
    operation_id="sw_009",
    summary="발행 처리 결과 ACK",
)
async def acknowledge_publish(
    content_id: Annotated[str, Path(min_length=1, max_length=128)],
    payload: PublishAckRequest,
    service: PublishSnapshotService = Depends(get_publish_snapshot_service),
) -> PublishAckResponse:
    """[SW-009] Service Worker의 service-db 반영 결과를 Agent API에 기록한다."""
    return await sw_009(service, content_id, payload)


@router.post(
    "/publish-snapshot-batches/{batch_id}/ack",
    response_model=PublishBatchAckResponse,
    operation_id="sw_009_batch_ack",
    summary="Publish Snapshot Batch ACK",
    description=(
        "Service Worker가 service-db에 반영한 성공·재시도·최종 실패 결과를 "
        "항목별로 기록합니다. 같은 항목의 동일 ACK는 멱등하게 처리합니다."
    ),
)
async def acknowledge_publish_snapshot_batch(
    batch_id: Annotated[str, Path(min_length=1, max_length=64)],
    payload: PublishBatchAckRequest,
    service: PublishSnapshotService = Depends(get_publish_snapshot_service),
) -> PublishBatchAckResponse:
    """[SW-009] Publish Snapshot Batch의 부분 성공 ACK를 기록한다."""
    return await sw_009(service, batch_id, payload)
