"""PWIKI-013 개인 LLM Wiki 초기화 기능을 검증한다."""

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from domain.personal_wiki.documents.api import pwiki_013


class _FakeResetWriter:
    """초기화 요청 인자를 기록하는 저장소 대역."""

    def __init__(self) -> None:
        """호출 기록을 비어 있는 상태로 초기화한다."""
        self.call: tuple[str, str] | None = None

    async def reset_wiki(
        self, user_id: str, *, request_id: str
    ) -> Mapping[str, object]:
        """초기화 호출을 기록하고 빈 Wiki 결과를 반환한다."""
        self.call = (user_id, request_id)
        return {
            "reset_document_count": 0,
            "reset_relation_count": 0,
            "unsearchable_chunk_count": 0,
            "retired_wiki_version_count": 0,
            "retired_interest_profile_count": 0,
            "cancelled_job_count": 0,
            "reset_at": datetime(2026, 8, 10, tzinfo=UTC),
        }


def test_pwiki_013_resets_only_requested_user() -> None:
    """PWIKI-013이 사용자와 요청 ID를 저장소 경계에 전달하는지 검증한다."""
    writer = _FakeResetWriter()

    result = asyncio.run(pwiki_013(writer, "user-1", request_id="request-1"))

    assert writer.call == ("user-1", "request-1")
    assert result["reset_document_count"] == 0


@pytest.mark.parametrize(
    ("user_id", "request_id"),
    [("", "request-1"), ("user-1", "")],
)
def test_pwiki_013_requires_user_and_request_id(
    user_id: str, request_id: str
) -> None:
    """초기화 범위를 식별할 값이 없으면 저장소 호출 전에 실패한다."""
    with pytest.raises(ValueError):
        asyncio.run(pwiki_013(_FakeResetWriter(), user_id, request_id=request_id))
