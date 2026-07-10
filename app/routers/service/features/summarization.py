"""기능 구현 모듈.

SVC-009 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def svc_009(request: FeatureRequest) -> FeatureResult:
    """[SVC-009] 요약 요청.

    문서 또는 URL 요약을 요청한다.
    """
    raise NotImplementedError("[SVC-009] 기능 구현이 필요합니다.")
