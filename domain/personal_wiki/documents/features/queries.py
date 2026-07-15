"""개인 Wiki 문서와 관계 Graph 조회 기능.

PWIKI-003이 주입받은 영속 저장소 경계를 통해 사용자별 최신 Wiki 문서와
관계를 조회하고 공통 기능 결과로 반환한다.
"""

from typing import Mapping, Protocol, cast

from shared.contracts import FeatureRequest, FeatureResult


class WikiGraphReader(Protocol):
    """사용자 Wiki Graph를 영속 저장소에서 읽는 경계."""

    async def get_graph(self, user_id: str) -> Mapping[str, object]:
        """사용자의 현재 Wiki Graph를 반환한다."""
        ...


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def pwiki_003(request: FeatureRequest) -> FeatureResult:
    """[PWIKI-003] 개인 Wiki 문서 조회.

    사용자의 Wiki 문서 목록과 상세 내용을 조회한다.
    """
    if not request.user_id:
        raise ValueError("PWIKI-003에 user_id가 필요합니다.")
    reader_value = request.payload.get("reader")
    if reader_value is None or not hasattr(reader_value, "get_graph"):
        raise ValueError("PWIKI-003에 Wiki Graph 저장소가 필요합니다.")
    reader = cast(WikiGraphReader, reader_value)
    graph = await reader.get_graph(request.user_id)
    return FeatureResult(feature_id="PWIKI-003", data=graph)
