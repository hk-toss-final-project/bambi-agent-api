"""기능 구현 모듈.

SUM-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sum_012(request: FeatureRequest) -> FeatureResult:
    """[SUM-012] 요약 품질 평가.

    누락, 왜곡, 과장 여부를 검사한다.
    """
    raise NotImplementedError("[SUM-012] 기능 구현이 필요합니다.")
