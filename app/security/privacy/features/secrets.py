"""기능 구현 모듈.

SEC-008, SEC-009 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sec_008(request: FeatureRequest) -> FeatureResult:
    """[SEC-008] Secret 관리.

    Provider Key와 외부 API Key를 안전하게 관리한다.
    """
    raise NotImplementedError("[SEC-008] 기능 구현이 필요합니다.")


async def sec_009(request: FeatureRequest) -> FeatureResult:
    """[SEC-009] 외부 API Key 보호.

    API Key 원문을 저장하지 않고 Hash로 관리한다.
    """
    raise NotImplementedError("[SEC-009] 기능 구현이 필요합니다.")
