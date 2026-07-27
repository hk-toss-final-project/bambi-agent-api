"""WBA-015 삭제 반영 facade의 위임을 검증한다."""

import asyncio
from typing import Any

import pytest

from agent.wiki_builder.features import deletion


def test_wba_015_delegates_to_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    """wba_015가 영속화 함수에 인자를 그대로 위임하는지 검증한다."""
    captured: dict[str, Any] = {}

    async def fake_delete(connection: Any, **kwargs: Any) -> dict[str, object]:
        """호출 인자를 기록하고 고정 결과를 반환한다."""
        captured.update(kwargs)
        return {"document_id": "document-1", "already_deleted": False}

    monkeypatch.setattr(
        deletion, "delete_wiki_document_and_record_event", fake_delete
    )

    result = asyncio.run(
        deletion.wba_015(
            object(),  # type: ignore[arg-type]
            user_id="user-1",
            document_id="document-1",
            source_event_id="delete-1",
            memo="정리",
        )
    )

    assert result["document_id"] == "document-1"
    assert captured["user_id"] == "user-1"
    assert captured["source_event_id"] == "delete-1"
    assert captured["memo"] == "정리"
