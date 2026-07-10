"""기능 구현 모듈.

EXT-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ext_010(request: FeatureRequest) -> FeatureResult:
    """[EXT-010] API Scope 검증.

    요청 기능에 필요한 Scope를 확인한다.
    """
    raise NotImplementedError("[EXT-010] 기능 구현이 필요합니다.")
