"""개인 Wiki 문서 목록·상세와 관계 Graph 조회 기능 구현."""

from typing import Literal, Mapping, Protocol


class WikiGraphReader(Protocol):
    """사용자 Wiki Graph를 영속 저장소에서 읽는 경계."""

    async def get_graph(self, user_id: str) -> Mapping[str, object]:
        """사용자의 현재 Wiki Graph를 반환한다."""
        ...


class WikiDocumentReader(Protocol):
    """사용자 Wiki 문서 목록과 상세를 읽는 영속 저장소 경계."""

    async def list_documents(
        self,
        user_id: str,
        *,
        document_kind: str | None,
        limit: int,
        offset: int,
    ) -> Mapping[str, object]:
        """사용자의 현재 Wiki 문서 목록을 반환한다."""
        ...

    async def get_document(
        self, user_id: str, document_id: str
    ) -> Mapping[str, object] | None:
        """사용자의 현재 Wiki 문서 상세를 반환한다."""
        ...


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def pwiki_003(
    reader: WikiGraphReader | WikiDocumentReader,
    user_id: str,
    *,
    operation: Literal["graph", "list", "detail"],
    document_kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
    document_id: str | None = None,
) -> Mapping[str, object] | None:
    """[PWIKI-003] 개인 Wiki 문서 조회.

    사용자의 Wiki 문서 목록과 상세 내용을 조회한다.
    """
    if not user_id:
        raise ValueError("PWIKI-003에 user_id가 필요합니다.")
    if operation == "graph":
        if not hasattr(reader, "get_graph"):
            raise ValueError("PWIKI-003 Graph 조회 저장소가 필요합니다.")
        return await reader.get_graph(user_id)
    if operation == "list":
        if not hasattr(reader, "list_documents"):
            raise ValueError("PWIKI-003 문서 목록 조회 저장소가 필요합니다.")
        return await reader.list_documents(
            user_id,
            document_kind=document_kind,
            limit=limit,
            offset=offset,
        )
    if document_id is None:
        raise ValueError("PWIKI-003 상세 조회에 document_id가 필요합니다.")
    if not hasattr(reader, "get_document"):
        raise ValueError("PWIKI-003 문서 상세 조회 저장소가 필요합니다.")
    return await reader.get_document(user_id, document_id)
