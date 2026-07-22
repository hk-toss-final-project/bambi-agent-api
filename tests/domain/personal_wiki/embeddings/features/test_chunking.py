"""개인 Wiki Chunk 생성과 저장 기능의 typed 경계를 검증한다."""

import asyncio
from collections.abc import Sequence

from domain.personal_wiki.embeddings.features.chunking import pwe_001, pwe_002


class _FakeChunkRepository:
    """Chunk 저장 인자를 기록하는 저장소 대역."""

    def __init__(self) -> None:
        self.saved: dict[str, object] | None = None

    async def save_chunks(
        self,
        *,
        document_version_id: object,
        namespace_key: str,
        chunks: Sequence[str],
    ) -> int:
        """저장 인자를 기록하고 Chunk 수를 반환한다."""
        self.saved = {
            "document_version_id": document_version_id,
            "namespace_key": namespace_key,
            "chunks": list(chunks),
        }
        return len(chunks)


def test_pwe_001_preserves_heading_boundaries_and_size_limit() -> None:
    """두 번째 Heading을 새 Chunk로 시작하고 긴 본문은 제한 길이로 나눈다."""
    content = "# 제목\n소개\n## 첫째\nabcdefgh\n## 둘째\n마무리"

    chunks = asyncio.run(pwe_001(content, max_chars=12))

    assert all(len(chunk) <= 12 for chunk in chunks)
    assert any(chunk.startswith("## 둘째") for chunk in chunks)


def test_pwe_002_delegates_to_explicit_repository() -> None:
    """Chunk 저장 기능이 문서 Version과 Namespace를 저장소에 전달한다."""
    repository = _FakeChunkRepository()

    count = asyncio.run(
        pwe_002(
            repository,
            document_version_id="version-1",
            namespace_key="user/user-1",
            chunks=["첫째", "둘째"],
        )
    )

    assert count == 2
    assert repository.saved == {
        "document_version_id": "version-1",
        "namespace_key": "user/user-1",
        "chunks": ["첫째", "둘째"],
    }
