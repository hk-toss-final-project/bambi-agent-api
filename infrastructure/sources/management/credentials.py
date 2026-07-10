"""기능 구현 모듈.

GS-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def gs_011(request: FeatureRequest) -> FeatureResult:
    """[GS-011] 외부 API 인증정보 연결.

    Source 호출에 필요한 Secret을 연결한다.
    """
    raise NotImplementedError("[GS-011] 기능 구현이 필요합니다.")
