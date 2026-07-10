"""기능 구현 모듈.

DISC-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def disc_008(request: FeatureRequest) -> FeatureResult:
    """[DISC-008] 사용자 관심사 매칭.

    Global Source와 개인 관심사를 매칭한다.
    """
    raise NotImplementedError("[DISC-008] 기능 구현이 필요합니다.")
