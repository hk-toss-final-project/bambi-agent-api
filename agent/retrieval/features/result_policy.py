"""기능 구현 모듈.

RET-004, RET-005 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ret_004(request: FeatureRequest) -> FeatureResult:
    """[RET-004] Top-K 설정.

    검색 결과로 사용할 문서 수를 설정한다.
    """
    raise NotImplementedError("[RET-004] 기능 구현이 필요합니다.")


async def ret_005(request: FeatureRequest) -> FeatureResult:
    """[RET-005] Reranking 설정.

    검색 결과 재정렬 모델과 정책을 설정한다.
    """
    raise NotImplementedError("[RET-005] 기능 구현이 필요합니다.")
