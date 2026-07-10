"""Global Source Connector가 따르는 공통 입력과 출력 계약."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Protocol, Sequence


@dataclass(frozen=True, slots=True)
class SourceQuery:
    """외부 Source 수집에 사용하는 검색 조건."""

    keywords: Sequence[str]
    language: str | None = None
    collected_after: datetime | None = None
    options: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """Source별 응답을 정규화하기 전의 최소 수집 문서."""

    source_type: str
    external_id: str
    url: str
    title: str
    raw_payload: Mapping[str, object] = field(default_factory=dict)


class SourceConnector(Protocol):
    """외부 Source의 신규 문서를 수집하는 Connector 인터페이스."""

    async def collect(self, query: SourceQuery) -> list[SourceDocument]:
        """검색 조건에 맞는 외부 문서를 수집해 공통 원시 문서로 반환한다."""
        ...
