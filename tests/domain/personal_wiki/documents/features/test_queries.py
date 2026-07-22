"""PWIKI-003 개인 Wiki Graph 기능 함수를 검증한다."""

import asyncio
from collections.abc import Mapping

import pytest

from domain.personal_wiki.documents.features.queries import pwiki_003


class _FakeGraphReader:
    """조회한 사용자 ID를 기록하는 Wiki Graph 저장소 대역."""

    def __init__(self) -> None:
        """아직 조회하지 않은 상태로 사용자 ID를 초기화한다."""
        self.user_id: str | None = None

    async def get_graph(self, user_id: str) -> Mapping[str, object]:
        """빈 Graph와 조회 사용자 ID를 반환한다."""
        self.user_id = user_id
        return {
            "user_id": user_id,
            "namespace_key": f"user/{user_id}",
            "stats": {
                "node_count": 0,
                "edge_count": 0,
                "entity_count": 0,
                "concept_count": 0,
                "orphan_count": 0,
            },
            "nodes": [],
            "edges": [],
        }


def test_pwiki_003_reads_user_graph() -> None:
    """PWIKI-003이 사용자 ID를 Repository에 전달하고 기능 결과를 반환한다."""
    reader = _FakeGraphReader()

    result = asyncio.run(pwiki_003(reader, "user-1", operation="graph"))

    assert reader.user_id == "user-1"
    assert result["namespace_key"] == "user/user-1"


def test_pwiki_003_requires_user_and_repository() -> None:
    """사용자 또는 Graph 저장소가 없으면 DB 조회 전에 실패한다."""
    with pytest.raises(ValueError, match="user_id"):
        asyncio.run(pwiki_003(_FakeGraphReader(), "", operation="graph"))
    with pytest.raises(ValueError, match="저장소"):
        asyncio.run(pwiki_003(object(), "user-1", operation="graph"))  # type: ignore[call-overload]
