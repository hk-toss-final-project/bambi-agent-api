"""Service Worker가 호출하는 발행 Snapshot과 ACK 내부 라우터."""

from typing import Annotated, TypeVar, cast

from fastapi import APIRouter, Depends, Path, Request

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
from app.services.publish_snapshots import PublishSnapshotService
from shared.contracts import FeatureRequest, FeatureResult

router = APIRouter(tags=["service-worker"])
ResponseT = TypeVar("ResponseT")


def _request_id(request: Request) -> str:
    """추적 미들웨어가 생성한 Request ID를 반환한다."""
    return request.state.request_id


def _feature_response(
    result: FeatureResult,
    response_type: type[ResponseT],
) -> ResponseT:
    """기능 결과에 담긴 Service Worker 응답 객체를 검증해 반환한다."""
    response = result.data.get("result")
    if not isinstance(response, response_type):
        raise RuntimeError(
            f"{result.feature_id}가 예상 응답 {response_type.__name__}을 반환하지 않았습니다."
        )
    return cast(ResponseT, response)


@router.get(
    "/publish-snapshots/{content_id}",
    response_model=PublishSnapshotResponse,
    operation_id="sw_004",
    summary="최신 Publish Snapshot 조회",
)
async def get_publish_snapshot(
    content_id: Annotated[str, Path(min_length=1, max_length=128)],
    request: Request,
    service: PublishSnapshotService = Depends(get_publish_snapshot_service),
) -> PublishSnapshotResponse:
    """[SW-004] service-db 저장에 사용할 최신 Publish Snapshot을 반환한다."""
    result = await sw_004(
        FeatureRequest(
            request_id=_request_id(request),
            actor_id="service-worker",
            payload={
                "implementation": lambda: service.get_publish_snapshot(content_id)
            },
        )
    )
    return _feature_response(result, PublishSnapshotResponse)


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
    request: Request,
    service: PublishSnapshotService = Depends(get_publish_snapshot_service),
) -> PublishBatchClaimResponse:
    """[SW-004] 준비된 Publish Snapshot을 Lease와 함께 Batch Claim한다."""
    result = await sw_004(
        FeatureRequest(
            request_id=_request_id(request),
            actor_id=payload.worker_id,
            payload={
                "implementation": lambda: service.claim_publish_snapshot_batch(payload)
            },
        )
    )
    return _feature_response(result, PublishBatchClaimResponse)


@router.post(
    "/publish-snapshots/{content_id}/ack",
    response_model=PublishAckResponse,
    operation_id="sw_009",
    summary="발행 처리 결과 ACK",
)
async def acknowledge_publish(
    content_id: Annotated[str, Path(min_length=1, max_length=128)],
    payload: PublishAckRequest,
    request: Request,
    service: PublishSnapshotService = Depends(get_publish_snapshot_service),
) -> PublishAckResponse:
    """[SW-009] Service Worker의 service-db 반영 결과를 Agent API에 기록한다."""
    result = await sw_009(
        FeatureRequest(
            request_id=_request_id(request),
            actor_id="service-worker",
            payload={
                "implementation": lambda: service.acknowledge_publish(
                    content_id, payload
                )
            },
        )
    )
    return _feature_response(result, PublishAckResponse)


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
    request: Request,
    service: PublishSnapshotService = Depends(get_publish_snapshot_service),
) -> PublishBatchAckResponse:
    """[SW-009] Publish Snapshot Batch의 부분 성공 ACK를 기록한다."""
    result = await sw_009(
        FeatureRequest(
            request_id=_request_id(request),
            actor_id=payload.worker_id,
            payload={
                "implementation": lambda: service.acknowledge_publish_snapshot_batch(
                    batch_id, payload
                )
            },
        )
    )
    return _feature_response(result, PublishBatchAckResponse)
