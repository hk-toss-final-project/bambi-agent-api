"""[COL-004] news_api Global Source Connector 스캐폴드."""

from infrastructure.sources.connectors.base import SourceDocument, SourceQuery


# MVP: COL-004 외부 데이터 자동 수집 범위에서 구현합니다.
async def collect_news_api(query: SourceQuery) -> list[SourceDocument]:
    """[COL-004] NewsAPI에서 뉴스 기사와 관련 Metadata를 수집한다."""
    raise NotImplementedError("[COL-004] Source Connector 구현이 필요합니다.")
