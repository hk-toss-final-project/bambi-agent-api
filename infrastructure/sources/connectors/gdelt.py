"""[COL-003] gdelt Global Source Connector 스캐폴드."""

from infrastructure.sources.connectors.base import SourceDocument, SourceQuery


# MVP: COL-003 외부 데이터 자동 수집 범위에서 구현합니다.
async def collect_gdelt(query: SourceQuery) -> list[SourceDocument]:
    """[COL-003] GDELT에서 글로벌 뉴스와 이벤트 데이터를 수집한다."""
    raise NotImplementedError("[COL-003] Source Connector 구현이 필요합니다.")
