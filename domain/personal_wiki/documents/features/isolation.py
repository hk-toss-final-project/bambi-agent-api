"""기능 구현 모듈.

PWIKI-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def pwiki_012(request: FeatureRequest) -> FeatureResult:
    """[PWIKI-012] 개인 Wiki 사용자 격리.

    다른 사용자의 개인 Wiki에 접근하지 못하도록 격리한다.
    """
    raise NotImplementedError("[PWIKI-012] 기능 구현이 필요합니다.")
