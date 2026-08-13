"""Service Worker Publish Snapshot 조회 기능."""

from typing import Protocol

from app.schemas.mvp import (
    PublishBatchClaimRequest,
    PublishBatchClaimResponse,
    PublishSnapshotResponse,
)


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
