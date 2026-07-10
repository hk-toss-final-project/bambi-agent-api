"""기능 구현 모듈.

EXT-011, EXT-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ext_011(request: FeatureRequest) -> FeatureResult:
    """[EXT-011] API Quota 검증.

    API Key의 사용량 한도를 확인한다.
    """
    raise NotImplementedError("[EXT-011] 기능 구현이 필요합니다.")


async def ext_012(request: FeatureRequest) -> FeatureResult:
    """[EXT-012] API Rate Limit.

    외부 호출량을 제한한다.
    """
    raise NotImplementedError("[EXT-012] 기능 구현이 필요합니다.")
