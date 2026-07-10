"""[COL-010] arxiv Global Source Connector 스캐폴드."""

from infrastructure.sources.connectors.base import SourceDocument, SourceQuery


async def collect_arxiv(query: SourceQuery) -> list[SourceDocument]:
    """[COL-010] arXiv 논문 Metadata, 초록과 본문을 수집한다."""
    raise NotImplementedError("[COL-010] Source Connector 구현이 필요합니다.")
