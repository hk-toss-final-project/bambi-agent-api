"""Publish Snapshot 저장소 계약과 인메모리 구현.

Service Worker용 Snapshot 조회·ACK 로직이 저장 방식에 의존하지 않도록
애플리케이션 서비스에서 사용하는 저장소 경계를 정의한다.
"""

from asyncio import Lock
from datetime import UTC, datetime
from typing import Protocol

from app.schemas.mvp import (
    PublishAckRequest,
    PublishSnapshotResponse,
)


def utc_now() -> datetime:
    """Timezone 정보가 포함된 현재 UTC 시각을 반환한다."""
    return datetime.now(UTC)


class PublishSnapshotNotFoundError(LookupError):
    """조회하거나 저장할 Publish Snapshot 원천이 없음을 나타낸다."""


class PublishSnapshotMismatchError(ValueError):
    """ACK의 버전 또는 Hash가 최신 Snapshot과 다름을 나타낸다."""


class StalePublishSnapshotError(ValueError):
    """현재 버전보다 오래된 Snapshot 저장 시도를 나타낸다."""


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


class InMemoryPublishSnapshotRepository:
    """외부 DB 없이 API 계약을 검증하는 인메모리 Snapshot 저장소."""

    def __init__(self) -> None:
        """Snapshot과 ACK 상태를 저장할 메모리 구조를 초기화한다."""
        self._snapshots: dict[str, PublishSnapshotResponse] = {}
        self._acknowledged_at: dict[str, datetime] = {}
        self._lock = Lock()

    async def save(self, snapshot: PublishSnapshotResponse) -> None:
        """현재보다 새로운 버전의 Snapshot만 메모리에 저장한다."""
        async with self._lock:
            current = self._snapshots.get(snapshot.content_id)
            if current and snapshot.version <= current.version:
                raise StalePublishSnapshotError(snapshot.content_id)
            self._snapshots[snapshot.content_id] = snapshot

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
            return acknowledged_at
