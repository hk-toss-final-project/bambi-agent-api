"""[COL-006] blog Global Source Connector 스캐폴드."""

from infrastructure.sources.connectors.base import SourceDocument, SourceQuery


async def collect_blog(query: SourceQuery) -> list[SourceDocument]:
    """[COL-006] 블로그와 공개 게시글 데이터를 수집한다."""
    raise NotImplementedError("[COL-006] Source Connector 구현이 필요합니다.")
