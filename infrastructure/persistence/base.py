"""Agent DB와 Vector 저장소 접근을 위한 추상 인터페이스."""

from collections.abc import Mapping, Sequence
from typing import Protocol


class AgentRepository(Protocol):
    """Agent DB의 도메인 데이터 저장과 조회 경계."""

    async def get(self, resource: str, resource_id: str) -> Mapping[str, object] | None:
        """리소스 종류와 식별자로 단일 Agent DB 레코드를 조회한다."""
        ...

    async def save(self, resource: str, data: Mapping[str, object]) -> str:
        """Agent DB에 도메인 레코드를 저장하고 식별자를 반환한다."""
        ...


class VectorRepository(Protocol):
    """사용자별·Global Namespace의 Vector 저장과 검색 경계."""

    async def upsert(
        self,
        namespace: str,
        vectors: Sequence[Mapping[str, object]],
    ) -> None:
        """Namespace에 Vector와 Metadata를 추가하거나 갱신한다."""
        ...

    async def search(
        self,
        namespace: str,
        vector: Sequence[float],
        *,
        top_k: int,
    ) -> list[Mapping[str, object]]:
        """지정 Namespace에서 의미 유사도 검색을 수행한다."""
        ...


class UnitOfWork(Protocol):
    """DB 변경과 Outbox 저장을 하나의 트랜잭션으로 묶는 경계."""

    async def commit(self) -> None:
        """현재 작업 단위의 모든 변경을 확정한다."""
        ...

    async def rollback(self) -> None:
        """현재 작업 단위에서 수행한 변경을 취소한다."""
        ...
