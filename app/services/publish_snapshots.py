"""Publish Snapshot 저장소 계약, 인메모리 구현과 애플리케이션 서비스.

Service Worker용 Snapshot 조회·ACK 로직이 저장 방식에 의존하지 않도록
저장소 경계를 정의하고, 저장소 오류를 API 공통 오류로 변환하는
PublishSnapshotService를 제공한다.
"""

from asyncio import Lock
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from fastapi import status

from app.exceptions import AgentApiError, ErrorDetail
from app.schemas.mvp import (
    PublishAckRequest,
    PublishAckResponse,
    PublishBatchAckItemRequest,
    PublishBatchAckItemResponse,
    PublishBatchAckRequest,
    PublishBatchAckResponse,
    PublishBatchClaimRequest,
    PublishBatchClaimResponse,
    PublishBatchResultStatus,
    PublishSnapshotResponse,
    PublishStatus,
)

MAX_PUBLISH_ATTEMPTS = 5
PUBLISH_RETRY_BASE_SECONDS = 30
PUBLISH_RETRY_MAX_SECONDS = 3600


def utc_now() -> datetime:
    """Timezone 정보가 포함된 현재 UTC 시각을 반환한다."""
    return datetime.now(UTC)


class PublishSnapshotNotFoundError(LookupError):
    """조회하거나 저장할 Publish Snapshot 원천이 없음을 나타낸다."""


class PublishSnapshotMismatchError(ValueError):
    """ACK의 버전 또는 Hash가 최신 Snapshot과 다름을 나타낸다."""


class StalePublishSnapshotError(ValueError):
    """현재 버전보다 오래된 Snapshot 저장 시도를 나타낸다."""


class PublishBatchNotFoundError(LookupError):
    """요청한 Publish Snapshot Batch Claim이 없음을 나타낸다."""


class PublishBatchOwnershipMismatchError(ValueError):
    """Batch를 Claim한 Worker와 ACK Worker가 다름을 나타낸다."""


class PublishBatchLeaseExpiredError(ValueError):
    """Publish Snapshot Batch의 처리 Lease가 만료되었음을 나타낸다."""


def publish_retry_delay(attempt_count: int) -> timedelta:
    """발행 시도 횟수에 따른 지수 Backoff 시간을 반환한다."""
    seconds = min(
        PUBLISH_RETRY_BASE_SECONDS * (2 ** max(attempt_count - 1, 0)),
        PUBLISH_RETRY_MAX_SECONDS,
    )
    return timedelta(seconds=seconds)


def build_batch_ack_response(
    batch_id: str,
    results: list[PublishBatchAckItemResponse],
    acknowledged_at: datetime,
) -> PublishBatchAckResponse:
    """항목별 ACK 결과를 집계한 Batch 응답을 생성한다."""
    return PublishBatchAckResponse(
        batch_id=batch_id,
        published_count=sum(
            result.result is PublishBatchResultStatus.PUBLISHED for result in results
        ),
        retry_scheduled_count=sum(
            result.result is PublishBatchResultStatus.RETRY_SCHEDULED
            for result in results
        ),
        failed_count=sum(
            result.result is PublishBatchResultStatus.FAILED for result in results
        ),
        results=results,
        acknowledged_at=acknowledged_at,
    )


class PublishSnapshotRepository(Protocol):
    """Publish Snapshot 저장과 발행 ACK에 필요한 저장소 계약."""

    async def save(self, snapshot: PublishSnapshotResponse) -> None:
        """새로운 버전의 Publish Snapshot을 저장한다."""
        ...

    async def get_latest(self, content_id: str) -> PublishSnapshotResponse | None:
        """콘텐츠의 최신 Publish Snapshot을 반환한다."""
        ...

    async def acknowledge(
        self, content_id: str, payload: PublishAckRequest
    ) -> datetime:
        """최신 Snapshot을 검증하고 발행 처리 결과를 기록한다."""
        ...

    async def claim_batch(
        self, payload: PublishBatchClaimRequest
    ) -> PublishBatchClaimResponse:
        """처리 가능한 Publish Snapshot을 Lease와 함께 Batch Claim한다."""
        ...

    async def acknowledge_batch(
        self, batch_id: str, payload: PublishBatchAckRequest
    ) -> PublishBatchAckResponse:
        """Batch Claim의 항목별 발행 결과를 기록한다."""
        ...


@dataclass(slots=True)
class _InMemoryDeliveryState:
    """인메모리 Snapshot의 발행 Claim과 재시도 상태."""

    status: str = "ready"
    claim_id: str | None = None
    claimed_by: str | None = None
    lease_expires_at: datetime | None = None
    attempt_count: int = 0
    next_attempt_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class _InMemoryBatchClaim:
    """인메모리에 보존하는 Batch 소유권과 Lease."""

    worker_id: str
    lease_expires_at: datetime


@dataclass(frozen=True, slots=True)
class _InMemoryBatchAck:
    """중복 Batch ACK에 동일 결과를 반환하기 위한 항목별 기록."""

    request: PublishBatchAckItemRequest
    response: PublishBatchAckItemResponse
    acknowledged_at: datetime


class InMemoryPublishSnapshotRepository:
    """외부 DB 없이 API 계약을 검증하는 인메모리 Snapshot 저장소."""

    def __init__(self) -> None:
        """Snapshot과 ACK 상태를 저장할 메모리 구조를 초기화한다."""
        self._snapshots: dict[str, PublishSnapshotResponse] = {}
        self._acknowledged_at: dict[str, datetime] = {}
        self._delivery_states: dict[str, _InMemoryDeliveryState] = {}
        self._batch_claims: dict[str, _InMemoryBatchClaim] = {}
        self._batch_acks: dict[tuple[str, str, int], _InMemoryBatchAck] = {}
        self._lock = Lock()

    async def save(self, snapshot: PublishSnapshotResponse) -> None:
        """현재보다 새로운 버전의 Snapshot만 메모리에 저장한다."""
        async with self._lock:
            current = self._snapshots.get(snapshot.content_id)
            if current and snapshot.version <= current.version:
                raise StalePublishSnapshotError(snapshot.content_id)
            self._snapshots[snapshot.content_id] = snapshot
            self._delivery_states[snapshot.content_id] = _InMemoryDeliveryState()

    async def get_latest(self, content_id: str) -> PublishSnapshotResponse | None:
        """식별자에 해당하는 최신 Snapshot을 메모리에서 조회한다."""
        return self._snapshots.get(content_id)

    async def acknowledge(
        self, content_id: str, payload: PublishAckRequest
    ) -> datetime:
        """Snapshot 버전과 Hash를 확인하고 ACK 시각을 저장한다."""
        async with self._lock:
            snapshot = self._snapshots.get(content_id)
            if snapshot is None:
                raise PublishSnapshotNotFoundError(content_id)
            if (
                payload.version != snapshot.version
                or payload.snapshot_hash != snapshot.snapshot_hash
            ):
                raise PublishSnapshotMismatchError(content_id)
            acknowledged_at = utc_now()
            self._acknowledged_at[content_id] = acknowledged_at
            state = self._delivery_states[content_id]
            state.status = payload.status.value
            state.claim_id = None
            state.claimed_by = None
            state.lease_expires_at = None
            return acknowledged_at

    async def claim_batch(
        self, payload: PublishBatchClaimRequest
    ) -> PublishBatchClaimResponse:
        """처리 가능한 Snapshot을 생성 시각 순으로 Lease와 함께 점유한다."""
        async with self._lock:
            now = utc_now()
            eligible = [
                snapshot
                for snapshot in self._snapshots.values()
                if self._is_claimable(snapshot.content_id, now)
            ]
            eligible.sort(key=lambda snapshot: (snapshot.created_at, snapshot.content_id))
            selected = eligible[: payload.limit]
            if not selected:
                return PublishBatchClaimResponse(worker_id=payload.worker_id)

            batch_id = str(uuid4())
            lease_expires_at = now + timedelta(seconds=payload.lease_seconds)
            self._batch_claims[batch_id] = _InMemoryBatchClaim(
                worker_id=payload.worker_id,
                lease_expires_at=lease_expires_at,
            )
            for snapshot in selected:
                state = self._delivery_states[snapshot.content_id]
                state.status = "claimed"
                state.claim_id = batch_id
                state.claimed_by = payload.worker_id
                state.lease_expires_at = lease_expires_at
                state.attempt_count += 1
                state.next_attempt_at = None

            return PublishBatchClaimResponse(
                batch_id=batch_id,
                worker_id=payload.worker_id,
                lease_expires_at=lease_expires_at,
                items=selected,
            )

    def _is_claimable(self, content_id: str, now: datetime) -> bool:
        """Snapshot이 현재 새 Batch에 포함될 수 있는지 확인한다."""
        state = self._delivery_states[content_id]
        if state.status == "ready":
            return state.next_attempt_at is None or state.next_attempt_at <= now
        return (
            state.status == "claimed"
            and state.lease_expires_at is not None
            and state.lease_expires_at <= now
        )

    async def acknowledge_batch(
        self, batch_id: str, payload: PublishBatchAckRequest
    ) -> PublishBatchAckResponse:
        """Batch 소유권과 Lease를 확인하고 항목별 ACK를 멱등하게 기록한다."""
        async with self._lock:
            claim = self._batch_claims.get(batch_id)
            if claim is None:
                raise PublishBatchNotFoundError(batch_id)
            if claim.worker_id != payload.worker_id:
                raise PublishBatchOwnershipMismatchError(batch_id)

            cached = self._get_cached_batch_acks(batch_id, payload)
            if len(cached) == len(payload.items):
                return build_batch_ack_response(
                    batch_id,
                    [ack.response for ack in cached],
                    max(ack.acknowledged_at for ack in cached),
                )

            now = utc_now()
            if claim.lease_expires_at <= now:
                raise PublishBatchLeaseExpiredError(batch_id)

            results: list[PublishBatchAckItemResponse] = []
            acknowledged_at = now
            for item in payload.items:
                key = (batch_id, item.content_id, item.version)
                if cached_ack := self._batch_acks.get(key):
                    results.append(cached_ack.response)
                    acknowledged_at = max(
                        acknowledged_at, cached_ack.acknowledged_at
                    )
                    continue
                response = self._acknowledge_batch_item(batch_id, item, now)
                self._batch_acks[key] = _InMemoryBatchAck(
                    request=item,
                    response=response,
                    acknowledged_at=now,
                )
                results.append(response)

            return build_batch_ack_response(batch_id, results, acknowledged_at)

    def _get_cached_batch_acks(
        self, batch_id: str, payload: PublishBatchAckRequest
    ) -> list[_InMemoryBatchAck]:
        """요청과 완전히 일치하는 기존 항목별 ACK를 순서대로 반환한다."""
        cached: list[_InMemoryBatchAck] = []
        for item in payload.items:
            key = (batch_id, item.content_id, item.version)
            if existing := self._batch_acks.get(key):
                if existing.request != item:
                    raise PublishSnapshotMismatchError(item.content_id)
                cached.append(existing)
        return cached

    def _acknowledge_batch_item(
        self,
        batch_id: str,
        item: PublishBatchAckItemRequest,
        acknowledged_at: datetime,
    ) -> PublishBatchAckItemResponse:
        """Claim된 Snapshot 한 건을 발행 완료·재시도·최종 실패로 전환한다."""
        snapshot = self._snapshots.get(item.content_id)
        state = self._delivery_states.get(item.content_id)
        if (
            snapshot is None
            or state is None
            or snapshot.version != item.version
            or snapshot.snapshot_hash != item.snapshot_hash
            or state.claim_id != batch_id
        ):
            raise PublishSnapshotMismatchError(item.content_id)

        if item.status is PublishStatus.PUBLISHED:
            state.status = "published"
            result = PublishBatchResultStatus.PUBLISHED
            self._acknowledged_at[item.content_id] = acknowledged_at
        elif item.retryable and state.attempt_count < MAX_PUBLISH_ATTEMPTS:
            state.status = "ready"
            state.next_attempt_at = acknowledged_at + publish_retry_delay(
                state.attempt_count
            )
            result = PublishBatchResultStatus.RETRY_SCHEDULED
        else:
            state.status = "failed"
            result = PublishBatchResultStatus.FAILED

        state.claim_id = None
        state.claimed_by = None
        state.lease_expires_at = None
        return PublishBatchAckItemResponse(
            content_id=item.content_id,
            version=item.version,
            result=result,
        )
class PublishSnapshotService:
    """발행 Snapshot 조회·Claim·ACK를 실행하고 저장소 오류를 API 오류로 변환한다."""

    def __init__(self, repository: PublishSnapshotRepository) -> None:
        """발행 Snapshot 저장소를 주입한다."""
        self._repository = repository

    async def save_publish_snapshot(self, snapshot: PublishSnapshotResponse) -> None:
        """Report Builder Worker가 생성한 최신 발행 Snapshot을 저장한다."""
        try:
            await self._repository.save(snapshot)
        except StalePublishSnapshotError as exc:
            raise AgentApiError(
                status.HTTP_409_CONFLICT,
                ErrorDetail(
                    code="STALE_SNAPSHOT_VERSION",
                    message="현재보다 새로운 Snapshot 버전이 필요합니다.",
                ),
            ) from exc

    async def get_publish_snapshot(self, content_id: str) -> PublishSnapshotResponse:
        """Service Worker가 저장할 최신 발행 Snapshot을 반환한다."""
        if snapshot := await self._repository.get_latest(content_id):
            return snapshot
        raise AgentApiError(
            status.HTTP_404_NOT_FOUND,
            ErrorDetail(
                code="PUBLISH_SNAPSHOT_NOT_FOUND",
                message="발행 Snapshot을 찾을 수 없습니다.",
            ),
        )

    async def acknowledge_publish(
        self, content_id: str, payload: PublishAckRequest
    ) -> PublishAckResponse:
        """Snapshot 버전과 Hash를 확인한 뒤 Service Worker의 발행 ACK를 기록한다."""
        try:
            acknowledged_at = await self._repository.acknowledge(content_id, payload)
        except PublishSnapshotNotFoundError as exc:
            raise AgentApiError(
                status.HTTP_404_NOT_FOUND,
                ErrorDetail(
                    code="PUBLISH_SNAPSHOT_NOT_FOUND",
                    message="발행 Snapshot을 찾을 수 없습니다.",
                ),
            ) from exc
        except PublishSnapshotMismatchError as exc:
            raise AgentApiError(
                status.HTTP_409_CONFLICT,
                ErrorDetail(
                    code="PUBLISH_SNAPSHOT_MISMATCH",
                    message="ACK의 Snapshot 버전 또는 Hash가 일치하지 않습니다.",
                ),
            ) from exc
        return PublishAckResponse(
            content_id=content_id,
            version=payload.version,
            status=payload.status,
            acknowledged_at=acknowledged_at,
        )

    async def claim_publish_snapshot_batch(
        self, payload: PublishBatchClaimRequest
    ) -> PublishBatchClaimResponse:
        """Service Worker가 처리할 Publish Snapshot Batch를 Lease와 함께 반환한다."""
        return await self._repository.claim_batch(payload)

    async def acknowledge_publish_snapshot_batch(
        self, batch_id: str, payload: PublishBatchAckRequest
    ) -> PublishBatchAckResponse:
        """Service Worker의 항목별 Batch 발행 결과를 저장소에 반영한다."""
        try:
            return await self._repository.acknowledge_batch(batch_id, payload)
        except PublishBatchNotFoundError as exc:
            raise AgentApiError(
                status.HTTP_404_NOT_FOUND,
                ErrorDetail(
                    code="PUBLISH_BATCH_NOT_FOUND",
                    message="Publish Snapshot Batch를 찾을 수 없습니다.",
                ),
            ) from exc
        except PublishBatchOwnershipMismatchError as exc:
            raise AgentApiError(
                status.HTTP_409_CONFLICT,
                ErrorDetail(
                    code="PUBLISH_BATCH_OWNERSHIP_MISMATCH",
                    message="Batch를 Claim한 Worker와 ACK Worker가 다릅니다.",
                ),
            ) from exc
        except PublishBatchLeaseExpiredError as exc:
            raise AgentApiError(
                status.HTTP_409_CONFLICT,
                ErrorDetail(
                    code="PUBLISH_BATCH_LEASE_EXPIRED",
                    message="Batch Lease가 만료되어 ACK를 반영할 수 없습니다.",
                    retryable=True,
                ),
            ) from exc
        except PublishSnapshotMismatchError as exc:
            raise AgentApiError(
                status.HTTP_409_CONFLICT,
                ErrorDetail(
                    code="PUBLISH_SNAPSHOT_MISMATCH",
                    message="ACK 항목의 Snapshot 버전 또는 Hash가 일치하지 않습니다.",
                ),
            ) from exc
