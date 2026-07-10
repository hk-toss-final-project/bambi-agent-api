"""[COL-008] krx Global Source Connector 스캐폴드."""

from infrastructure.sources.connectors.base import SourceDocument, SourceQuery


async def collect_krx(query: SourceQuery) -> list[SourceDocument]:
    """[COL-008] KRX에서 시장과 종목 데이터를 수집한다."""
    raise NotImplementedError("[COL-008] Source Connector 구현이 필요합니다.")
