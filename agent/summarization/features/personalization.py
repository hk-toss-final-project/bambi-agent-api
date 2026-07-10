"""기능 구현 모듈.

SUM-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sum_010(request: FeatureRequest) -> FeatureResult:
    """[SUM-010] 관심사 기반 요약.

    사용자가 관심 있는 관점에 맞춰 요약한다.
    """
    raise NotImplementedError("[SUM-010] 기능 구현이 필요합니다.")
