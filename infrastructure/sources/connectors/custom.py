"""[COL-012] custom Global Source Connector 스캐폴드."""

from infrastructure.sources.connectors.base import SourceDocument, SourceQuery


async def collect_custom(query: SourceQuery) -> list[SourceDocument]:
    """[COL-012] 등록된 사용자 정의 Source Connector를 실행한다."""
    raise NotImplementedError("[COL-012] Source Connector 구현이 필요합니다.")
