"""OpenAI Batch PostgreSQL 영속화와 custom_id 결과 결합을 검증한다."""

import asyncio
from typing import Any

from infrastructure.persistence.features.llm_batches import (
    EnqueueLlmBatchItemCommand,
    apply_llm_batch_result_lines,
    claim_llm_batch,
    enqueue_llm_batch_item,
)


class _FakeCursor:
    """fetchone·fetchall Row를 제공하는 Cursor Test Double."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        """반환할 Row 목록을 저장한다."""
        self._rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        """첫 Row 또는 None을 반환한다."""
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        """전체 Row 목록을 반환한다."""
        return self._rows


class _FakeConnection:
    """SQL을 기록하고 순서별 Cursor Row를 반환하는 연결 대역."""

    def __init__(self, responses: list[list[dict[str, Any]]]) -> None:
        """순서별 응답과 빈 SQL 기록을 초기화한다."""
        self._responses = list(responses)
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    async def execute(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> _FakeCursor:
        """SQL을 기록하고 다음 응답 Cursor를 반환한다."""
        self.executed.append((query, params))
        rows = self._responses.pop(0) if self._responses else []
        return _FakeCursor(rows)


def _command() -> EnqueueLlmBatchItemCommand:
    """Wiki Embedding Batch Item 등록 명령 예시를 만든다."""
    return EnqueueLlmBatchItemCommand(
        user_id="user-1",
        custom_id="wiki:version-1",
        endpoint="/v1/embeddings",
        model_name="text-embedding-3-small",
        workload="wiki_embedding",
        resource_type="wiki_document_version",
        resource_id="version-1",
        request_body={"model": "text-embedding-3-small", "input": ["본문"]},
    )


def test_enqueue_llm_batch_item_returns_existing_custom_id() -> None:
    """INSERT 충돌 시 같은 custom_id의 기존 Item을 조회해 멱등 결과를 반환한다."""
    connection = _FakeConnection(
        [
            [],
            [
                {
                    "item_id": "item-1",
                    "custom_id": "wiki:version-1",
                    "status": "submitted",
                    "batch_id": "batch-1",
                }
            ],
        ]
    )

    stored = asyncio.run(
        enqueue_llm_batch_item(connection, _command())  # type: ignore[arg-type]
    )

    assert stored.item_id == "item-1"
    assert stored.status == "submitted"
    assert len(connection.executed) == 2


def test_claim_llm_batch_groups_same_endpoint_model_and_workload() -> None:
    """Queue 첫 Item과 같은 그룹만 Claim해 로컬 Batch와 연결한다."""
    connection = _FakeConnection(
        [
            [
                {
                    "provider": "openai",
                    "endpoint": "/v1/embeddings",
                    "model_name": "text-embedding-3-small",
                    "workload": "wiki_embedding",
                }
            ],
            [
                {
                    "item_id": "item-2",
                    "custom_id": "wiki:2",
                    "request_body": {"input": ["둘"]},
                },
                {
                    "item_id": "item-1",
                    "custom_id": "wiki:1",
                    "request_body": {"input": ["하나"]},
                },
            ],
            [{"batch_id": "batch-local-1"}],
            [],
        ]
    )

    batch = asyncio.run(claim_llm_batch(connection, max_items=500))  # type: ignore[arg-type]

    assert batch is not None
    assert batch.batch_id == "batch-local-1"
    assert [item.custom_id for item in batch.items] == ["wiki:2", "wiki:1"]
    assert connection.executed[1][1][-1] == 500
    assert connection.executed[-1][1][1] == ["item-2", "item-1"]


def test_apply_llm_batch_results_joins_by_custom_id_and_requeues_missing() -> None:
    """뒤섞인 성공·오류를 custom_id로 반영하고 expired 미완료 Item만 재등록한다."""
    connection = _FakeConnection(
        [
            [{"id": "item-2"}],
            [{"id": "item-1"}],
            [{"status": "queued"}],
        ]
    )
    lines = [
        {
            "custom_id": "wiki:2",
            "response": {
                "status_code": 200,
                "request_id": "req-2",
                "body": {
                    "data": [{"embedding": [0.1, 0.2]}],
                    "usage": {"prompt_tokens": 7, "total_tokens": 7},
                },
            },
            "error": None,
        },
        {
            "custom_id": "wiki:1",
            "response": {"status_code": 429, "request_id": "req-1"},
            "error": {"code": "rate_limit_exceeded"},
        },
    ]

    counts = asyncio.run(
        apply_llm_batch_result_lines(
            connection,  # type: ignore[arg-type]
            batch_id="batch-local-1",
            lines=lines,
            terminal_status="expired",
        )
    )

    assert counts == {"completed": 1, "failed": 1, "requeued": 1}
    assert connection.executed[0][1][-1] == "wiki:2"
    assert connection.executed[1][1][-1] == "wiki:1"
    assert connection.executed[0][1][5:7] == (7, None)
