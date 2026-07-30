"""Service Worker 발행 연동 FastAPI MVP 엔드포인트를 검증한다."""

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.schemas.mvp import PublishSnapshotResponse
from app.services.publish_snapshots import PublishSnapshotService


def _save_snapshots(
    service: PublishSnapshotService, count: int = 3
) -> list[PublishSnapshotResponse]:
    """Batch API 테스트에 사용할 생성 시각 순 Snapshot을 저장한다."""
    base_time = datetime(2026, 7, 13, tzinfo=UTC)
    snapshots = [
        PublishSnapshotResponse(
            content_id=f"batch-content-{number}",
            user_id=f"batch-user-{number}",
            version=1,
            snapshot_hash=f"batch-hash-{number}",
            title=f"Batch title {number}",
            summary=f"Batch summary {number}",
            body=f"Batch body {number}",
            created_at=base_time + timedelta(seconds=number),
        )
        for number in range(1, count + 1)
    ]
    for snapshot in snapshots:
        asyncio.run(service.save_publish_snapshot(snapshot))
    return snapshots


def test_publish_snapshot_and_ack_flow(
    client: TestClient, publish_service: PublishSnapshotService
) -> None:
    """최신 Snapshot을 조회하고 일치하는 발행 ACK를 반영하는지 검증한다."""
    snapshot = PublishSnapshotResponse(
        content_id="content-1",
        user_id="user-1",
        version=1,
        snapshot_hash="hash-1",
        title="Generated title",
        summary="Generated summary",
        body="Generated body",
        created_at=datetime.now(UTC),
    )
    asyncio.run(publish_service.save_publish_snapshot(snapshot))

    fetched = client.get("/internal/v1/publish-snapshots/content-1")
    acknowledged = client.post(
        "/internal/v1/publish-snapshots/content-1/ack",
        json={"version": 1, "snapshot_hash": "hash-1", "status": "published"},
    )

    assert fetched.status_code == 200
    assert fetched.json()["snapshot_hash"] == "hash-1"
    assert acknowledged.status_code == 200
    assert acknowledged.json()["feature_id"] == "SW-009"
    assert acknowledged.json()["status"] == "published"


def test_publish_snapshot_carries_interest_tags(
    client: TestClient, publish_service: PublishSnapshotService
) -> None:
    """Snapshot 조회 응답이 카드 관심사 태그를 그대로 전달하는지 검증한다."""
    snapshot = PublishSnapshotResponse(
        content_id="content-tagged",
        user_id="user-1",
        version=1,
        snapshot_hash="hash-tagged",
        title="Generated title",
        summary="Generated summary",
        body="Generated body",
        tags=["코스피"],
        created_at=datetime.now(UTC),
    )
    asyncio.run(publish_service.save_publish_snapshot(snapshot))

    fetched = client.get("/internal/v1/publish-snapshots/content-tagged")

    assert fetched.status_code == 200
    assert fetched.json()["tags"] == ["코스피"]


def test_publish_snapshot_tags_default_to_empty_list() -> None:
    """태그 없이 만든 Snapshot이 빈 목록으로 직렬화되는지 검증한다."""
    snapshot = PublishSnapshotResponse(
        content_id="content-untagged",
        user_id="user-1",
        version=1,
        snapshot_hash="hash-untagged",
        title="Generated title",
        summary="Generated summary",
        body="Generated body",
        created_at=datetime.now(UTC),
    )

    assert snapshot.tags == []
    assert snapshot.model_dump()["tags"] == []


def test_publish_ack_rejects_snapshot_mismatch(
    client: TestClient, publish_service: PublishSnapshotService
) -> None:
    """버전이나 Hash가 다른 발행 ACK가 충돌 응답을 반환하는지 검증한다."""
    snapshot = PublishSnapshotResponse(
        content_id="content-2",
        user_id="user-2",
        version=2,
        snapshot_hash="hash-2",
        title="Title",
        summary="Summary",
        body="Body",
        created_at=datetime.now(UTC),
    )
    asyncio.run(publish_service.save_publish_snapshot(snapshot))

    response = client.post(
        "/internal/v1/publish-snapshots/content-2/ack",
        json={"version": 1, "snapshot_hash": "wrong", "status": "published"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PUBLISH_SNAPSHOT_MISMATCH"


def test_unknown_publish_snapshot_returns_not_found(client: TestClient) -> None:
    """존재하지 않는 Publish Snapshot 조회가 404를 반환하는지 검증한다."""
    response = client.get("/internal/v1/publish-snapshots/unknown-content")

    assert response.status_code == 404
    assert response.json()["code"] == "PUBLISH_SNAPSHOT_NOT_FOUND"


def test_claim_publish_snapshot_batch_returns_full_payload_in_order(
    client: TestClient, publish_service: PublishSnapshotService
) -> None:
    """Batch Claim이 생성 시각 순으로 제한된 전체 Snapshot을 반환하는지 검증한다."""
    _save_snapshots(publish_service)

    first = client.post(
        "/internal/v1/publish-snapshot-batches/claim",
        json={"worker_id": "worker-1", "limit": 2, "lease_seconds": 120},
    )
    second = client.post(
        "/internal/v1/publish-snapshot-batches/claim",
        json={"worker_id": "worker-2", "limit": 2, "lease_seconds": 120},
    )
    empty = client.post(
        "/internal/v1/publish-snapshot-batches/claim",
        json={"worker_id": "worker-3", "limit": 2, "lease_seconds": 120},
    )

    assert first.status_code == 200
    assert [item["content_id"] for item in first.json()["items"]] == [
        "batch-content-1",
        "batch-content-2",
    ]
    assert first.json()["items"][0]["body"] == "Batch body 1"
    assert first.json()["batch_id"]
    assert first.json()["lease_expires_at"]
    assert [item["content_id"] for item in second.json()["items"]] == [
        "batch-content-3"
    ]
    assert empty.json() == {
        "batch_id": None,
        "worker_id": "worker-3",
        "lease_expires_at": None,
        "items": [],
    }


def test_batch_ack_supports_partial_results_and_idempotency(
    client: TestClient, publish_service: PublishSnapshotService
) -> None:
    """Batch ACK가 성공·재시도·최종 실패와 중복 요청을 처리하는지 검증한다."""
    snapshots = _save_snapshots(publish_service, count=3)
    claimed = client.post(
        "/internal/v1/publish-snapshot-batches/claim",
        json={"worker_id": "worker-ack", "limit": 10, "lease_seconds": 120},
    ).json()
    payload = {
        "worker_id": "worker-ack",
        "items": [
            {
                "content_id": snapshots[0].content_id,
                "version": snapshots[0].version,
                "snapshot_hash": snapshots[0].snapshot_hash,
                "status": "published",
            },
            {
                "content_id": snapshots[1].content_id,
                "version": snapshots[1].version,
                "snapshot_hash": snapshots[1].snapshot_hash,
                "status": "failed",
                "retryable": True,
                "failure_reason": "service-db timeout",
            },
            {
                "content_id": snapshots[2].content_id,
                "version": snapshots[2].version,
                "snapshot_hash": snapshots[2].snapshot_hash,
                "status": "failed",
                "retryable": False,
                "failure_reason": "service-db validation failed",
            },
        ],
    }

    first = client.post(
        f"/internal/v1/publish-snapshot-batches/{claimed['batch_id']}/ack",
        json=payload,
    )
    duplicate = client.post(
        f"/internal/v1/publish-snapshot-batches/{claimed['batch_id']}/ack",
        json=payload,
    )

    assert first.status_code == 200
    assert first.json()["published_count"] == 1
    assert first.json()["retry_scheduled_count"] == 1
    assert first.json()["failed_count"] == 1
    assert [result["result"] for result in first.json()["results"]] == [
        "published",
        "retry_scheduled",
        "failed",
    ]
    assert duplicate.json() == first.json()


def test_batch_ack_rejects_different_worker(
    client: TestClient, publish_service: PublishSnapshotService
) -> None:
    """Batch를 점유하지 않은 Worker의 ACK를 충돌로 거부하는지 검증한다."""
    snapshot = _save_snapshots(publish_service, count=1)[0]
    claimed = client.post(
        "/internal/v1/publish-snapshot-batches/claim",
        json={"worker_id": "worker-owner"},
    ).json()

    response = client.post(
        f"/internal/v1/publish-snapshot-batches/{claimed['batch_id']}/ack",
        json={
            "worker_id": "worker-other",
            "items": [
                {
                    "content_id": snapshot.content_id,
                    "version": snapshot.version,
                    "snapshot_hash": snapshot.snapshot_hash,
                    "status": "published",
                }
            ],
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PUBLISH_BATCH_OWNERSHIP_MISMATCH"


def test_batch_ack_validates_failed_item_fields(
    client: TestClient, publish_service: PublishSnapshotService
) -> None:
    """실패 Batch ACK에 retryable과 failure_reason을 필수로 요구하는지 검증한다."""
    snapshot = _save_snapshots(publish_service, count=1)[0]
    claimed = client.post(
        "/internal/v1/publish-snapshot-batches/claim",
        json={"worker_id": "worker-validation"},
    ).json()

    response = client.post(
        f"/internal/v1/publish-snapshot-batches/{claimed['batch_id']}/ack",
        json={
            "worker_id": "worker-validation",
            "items": [
                {
                    "content_id": snapshot.content_id,
                    "version": 1,
                    "snapshot_hash": snapshot.snapshot_hash,
                    "status": "failed",
                }
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_VALIDATION_ERROR"
