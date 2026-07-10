"""기능 구현 모듈.

SEC-005, SEC-006 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sec_005(request: FeatureRequest) -> FeatureResult:
    """[SEC-005] 개인정보 최소 수집.

    AI 처리에 필요하지 않은 개인정보를 저장하지 않는다.
    """
    raise NotImplementedError("[SEC-005] 기능 구현이 필요합니다.")


async def sec_006(request: FeatureRequest) -> FeatureResult:
    """[SEC-006] 개인정보 제거.

    대화와 문서에서 불필요한 개인정보를 제거한다.
    """
    raise NotImplementedError("[SEC-006] 기능 구현이 필요합니다.")
