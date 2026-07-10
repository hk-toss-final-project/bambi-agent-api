"""기능 구현 모듈.

SUM-009 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sum_009(request: FeatureRequest) -> FeatureResult:
    """[SUM-009] 계층형 요약.

    Chunk 요약을 결합해 전체 요약을 생성한다.
    """
    raise NotImplementedError("[SUM-009] 기능 구현이 필요합니다.")
