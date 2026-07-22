"""개인 Wiki Graph 조회 애플리케이션 서비스.

FastAPI 요청 Context를 PWIKI-003 기능 계약으로 변환하고 Graph 응답
스키마를 검증해 라우터가 DB 구현 세부사항을 알지 않도록 한다.
"""

from typing import Mapping, Protocol

from app.schemas.wiki import WikiGraphResponse, WikiTopNode, WikiTopNodesResponse
from domain.personal_wiki.documents.api import pwiki_003


class WikiGraphRepository(Protocol):
    """개인 Wiki Graph를 조회하는 Repository 계약."""

    async def get_graph(self, user_id: str) -> Mapping[str, object]:
        """사용자 Namespace의 현재 Graph를 반환한다."""
        ...


class WikiGraphService:
    """PWIKI-003을 호출해 검증된 Graph API 응답을 만드는 서비스."""

    def __init__(self, repository: WikiGraphRepository) -> None:
        """개인 Wiki Graph Repository를 주입한다."""
        self._repository = repository

    async def get_graph(self, user_id: str, request_id: str) -> WikiGraphResponse:
        """사용자 Graph를 조회하고 Pydantic 응답으로 검증한다."""
        result = await pwiki_003(
            self._repository, user_id, operation="graph"
        )
        return WikiGraphResponse.model_validate(result)

    async def get_top_nodes(
        self, user_id: str, request_id: str, *, limit: int
    ) -> WikiTopNodesResponse:
        """연결 Edge가 많은 순서로 정렬한 상위 Node 목록을 반환한다.

        Args:
            user_id: 조회 대상 사용자 ID
            request_id: 추적용 Request ID
            limit: 반환할 최대 Node 수

        Returns:
            degree 내림차순, 같은 degree는 제목 오름차순으로 정렬한 Node 목록
        """
        graph = await self.get_graph(user_id, request_id)
        ranked = sorted(
            graph.nodes, key=lambda node: (-node.degree, node.title, node.id)
        )
        return WikiTopNodesResponse(
            user_id=graph.user_id,
            namespace_key=graph.namespace_key,
            wiki_version=graph.wiki_version,
            total_node_count=graph.stats.node_count,
            items=[
                WikiTopNode(
                    rank=index + 1,
                    document_id=node.id,
                    document_kind=node.document_kind,
                    document_key=node.document_key,
                    title=node.title,
                    subtype=node.subtype,
                    degree=node.degree,
                    summary=node.summary,
                    aliases=list(node.aliases),
                    file_path=node.file_path,
                )
                for index, node in enumerate(ranked[:limit])
            ],
        )
