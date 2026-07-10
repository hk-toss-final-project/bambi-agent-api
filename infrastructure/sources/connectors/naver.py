"""[COL-002] naver Global Source Connector 스캐폴드."""

from infrastructure.sources.connectors.base import SourceDocument, SourceQuery


# MVP: COL-002 외부 데이터 자동 수집 범위에서 구현합니다.
async def collect_naver(query: SourceQuery) -> list[SourceDocument]:
    """[COL-002] 설정된 키워드로 Naver API 데이터를 수집한다."""
    raise NotImplementedError("[COL-002] Source Connector 구현이 필요합니다.")
