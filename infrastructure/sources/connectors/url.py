"""[COL-011] url Global Source Connector 스캐폴드."""

from infrastructure.sources.connectors.base import SourceDocument, SourceQuery


async def collect_url(query: SourceQuery) -> list[SourceDocument]:
    """[COL-011] 관리자가 지정한 외부 URL의 데이터를 수집한다."""
    raise NotImplementedError("[COL-011] Source Connector 구현이 필요합니다.")
