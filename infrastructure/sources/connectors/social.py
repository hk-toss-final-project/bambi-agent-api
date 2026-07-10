"""[COL-005] social Global Source Connector 스캐폴드."""

from infrastructure.sources.connectors.base import SourceDocument, SourceQuery


async def collect_social(query: SourceQuery) -> list[SourceDocument]:
    """[COL-005] 허용된 SNS의 공개 데이터를 수집한다."""
    raise NotImplementedError("[COL-005] Source Connector 구현이 필요합니다.")
