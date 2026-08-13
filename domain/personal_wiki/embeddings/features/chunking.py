"""개인 Wiki Markdown Chunk 생성·저장 기능."""

from collections.abc import Sequence
from typing import Protocol


class WikiChunkRepository(Protocol):
    """개인 Wiki Chunk 저장에 필요한 영속 저장소 경계."""

    async def save_chunks(
        self,
        *,
        document_version_id: object,
        namespace_key: str,
        chunks: Sequence[str],
    ) -> int:
        """문서 Version의 검색 Chunk를 순서대로 저장한다."""
        ...


def chunk_wiki_markdown(content: str, *, max_chars: int = 2000) -> list[str]:
    """Wiki Markdown을 Heading 경계를 유지하는 검색용 Chunk로 나눈다."""
    if max_chars < 1:
        raise ValueError("Chunk 최대 글자 수는 1 이상이어야 합니다.")
    blocks: list[str] = []
    current: list[str] = []
    for line in content.splitlines():
        if line.startswith("## ") and current:
            blocks.append("\n".join(current).strip())
            current = []
        current.append(line)
    if current:
        blocks.append("\n".join(current).strip())

    chunks: list[str] = []
    for block in blocks:
        remaining = block
        while len(remaining) > max_chars:
            split_at = remaining.rfind("\n", 0, max_chars + 1)
            if split_at <= 0:
                split_at = max_chars
            chunks.append(remaining[:split_at].strip())
            remaining = remaining[split_at:].strip()
        if remaining:
            chunks.append(remaining)
    return chunks


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def pwe_001(content: str, *, max_chars: int = 2000) -> list[str]:
    """[PWE-001] 개인 Wiki 문서 Chunking.

    Wiki 문서를 의미 단위 Chunk로 분할한다.
    """
    return chunk_wiki_markdown(content, max_chars=max_chars)


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def pwe_002(
    repository: WikiChunkRepository,
    *,
    document_version_id: object,
    namespace_key: str,
    chunks: Sequence[str],
) -> int:
    """[PWE-002] Chunk 저장.

    생성된 Chunk를 문서 버전과 연결해 저장한다.
    """
    return await repository.save_chunks(
        document_version_id=document_version_id,
        namespace_key=namespace_key,
        chunks=chunks,
    )
