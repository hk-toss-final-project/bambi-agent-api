"""Service Worker Publish Snapshot ACK 기능."""

from typing import Protocol

from app.schemas.mvp import (
    PublishAckRequest,
    PublishAckResponse,
    PublishBatchAckRequest,
    PublishBatchAckResponse,
)


class PublishAcknowledgementService(Protocol):
    """단건·Batch Publish Snapshot ACK에 필요한 서비스 경계."""

    async def acknowledge_publish(
        self, content_id: str, payload: PublishAckRequest
    ) -> PublishAckResponse:
        """단건 Publish Snapshot의 반영 결과를 기록한다."""
        ...

    async def acknowledge_publish_snapshot_batch(
        self, batch_id: str, payload: PublishBatchAckRequest
    ) -> PublishBatchAckResponse:
        """Publish Snapshot Batch의 항목별 반영 결과를 기록한다."""
        ...


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sw_009(
    service: PublishAcknowledgementService,
    target_id: str,
    payload: PublishAckRequest | PublishBatchAckRequest,
) -> PublishAckResponse | PublishBatchAckResponse:
    """[SW-009] 발행 완료 ACK.

    service-db 반영 완료를 Agent API에 알린다.
    """
    if isinstance(payload, PublishAckRequest):
        return await service.acknowledge_publish(target_id, payload)
    return await service.acknowledge_publish_snapshot_batch(target_id, payload)
