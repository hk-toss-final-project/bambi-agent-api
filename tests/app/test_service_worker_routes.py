"""Service Worker 발행 연동 FastAPI MVP 엔드포인트를 검증한다."""

import asyncio
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.schemas.mvp import PublishSnapshotResponse
from app.services.mvp import AgentApiMvpService


def test_publish_snapshot_and_ack_flow(
    client: TestClient, mvp_service: AgentApiMvpService
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
    asyncio.run(mvp_service.save_publish_snapshot(snapshot))

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


def test_publish_ack_rejects_snapshot_mismatch(
    client: TestClient, mvp_service: AgentApiMvpService
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
    asyncio.run(mvp_service.save_publish_snapshot(snapshot))

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
