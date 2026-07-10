"""[COL-001] rss Global Source Connector 스캐폴드."""

from infrastructure.sources.connectors.base import SourceDocument, SourceQuery


async def collect_rss(query: SourceQuery) -> list[SourceDocument]:
    """[COL-001] 등록된 RSS Feed에서 신규 콘텐츠를 수집한다."""
    raise NotImplementedError("[COL-001] Source Connector 구현이 필요합니다.")
