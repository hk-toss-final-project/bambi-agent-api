"""[COL-009] github Global Source Connector 스캐폴드."""

from infrastructure.sources.connectors.base import SourceDocument, SourceQuery


async def collect_github(query: SourceQuery) -> list[SourceDocument]:
    """[COL-009] GitHub Repository, Release, Issue와 README를 수집한다."""
    raise NotImplementedError("[COL-009] Source Connector 구현이 필요합니다.")
