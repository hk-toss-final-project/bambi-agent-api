"""Service Worker Publish Snapshot 조회 기능과 미구현 검증 Scaffold."""

from typing import Protocol

from app.schemas.mvp import (
    PublishBatchClaimRequest,
    PublishBatchClaimResponse,
    PublishSnapshotResponse,
)
from shared.contracts import FeatureRequest, FeatureResult


class PublishSnapshotQueryService(Protocol):
    """Publish Snapshot 조회와 Batch Claim에 필요한 서비스 경계."""

    async def get_publish_snapshot(self, content_id: str) -> PublishSnapshotResponse:
        """콘텐츠의 최신 Publish Snapshot을 반환한다."""
        ...

    async def claim_publish_snapshot_batch(
        self, payload: PublishBatchClaimRequest
    ) -> PublishBatchClaimResponse:
        """처리할 Publish Snapshot Batch를 점유해 반환한다."""
        ...


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sw_004(
    service: PublishSnapshotQueryService,
    request: str | PublishBatchClaimRequest,
) -> PublishSnapshotResponse | PublishBatchClaimResponse:
    """[SW-004] Publish Snapshot 조회.

    Agent API에서 서비스 저장용 콘텐츠를 조회한다.
    """
    if isinstance(request, str):
        return await service.get_publish_snapshot(request)
    return await service.claim_publish_snapshot_batch(request)


async def sw_005(request: FeatureRequest) -> FeatureResult:
    """[SW-005] 발행 가능 상태 검증.

    콘텐츠가 실제 발행 가능한 상태인지 확인한다.
    """
    raise NotImplementedError("[SW-005] 기능 구현이 필요합니다.")


async def sw_006(request: FeatureRequest) -> FeatureResult:
    """[SW-006] 콘텐츠 Version 검증.

    오래된 콘텐츠 버전이 반영되지 않도록 확인한다.
    """
    raise NotImplementedError("[SW-006] 기능 구현이 필요합니다.")


async def sw_013(request: FeatureRequest) -> FeatureResult:
    """[SW-013] 콘텐츠 무결성 검증.

    Snapshot의 Hash와 버전을 확인한다.
    """
    raise NotImplementedError("[SW-013] 기능 구현이 필요합니다.")
