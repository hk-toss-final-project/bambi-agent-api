"""기능 구현 모듈.

REC-011, REC-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def rec_011(request: FeatureRequest) -> FeatureResult:
    """[REC-011] 추천 다양성 조정.

    특정 관심사에만 편중되지 않도록 조정한다.
    """
    raise NotImplementedError("[REC-011] 기능 구현이 필요합니다.")


async def rec_012(request: FeatureRequest) -> FeatureResult:
    """[REC-012] 추천 신선도 조정.

    오래된 콘텐츠의 추천 우선순위를 조정한다.
    """
    raise NotImplementedError("[REC-012] 기능 구현이 필요합니다.")
