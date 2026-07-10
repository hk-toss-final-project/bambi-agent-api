"""기능 구현 모듈.

PRAG-004 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def prag_004(request: FeatureRequest) -> FeatureResult:
    """[PRAG-004] 검색 결과 Reranking.

    사용자 관심사와 요청 목적을 기준으로 결과를 재정렬한다.
    """
    raise NotImplementedError("[PRAG-004] 기능 구현이 필요합니다.")
