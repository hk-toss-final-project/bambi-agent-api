"""기능 구현 모듈.

GS-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def gs_012(request: FeatureRequest) -> FeatureResult:
    """[GS-012] Source 사용량 제한 관리.

    외부 API별 호출량과 Quota를 관리한다.
    """
    raise NotImplementedError("[GS-012] 기능 구현이 필요합니다.")
