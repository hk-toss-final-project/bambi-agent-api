"""기능 구현 모듈.

SVC-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def svc_010(request: FeatureRequest) -> FeatureResult:
    """[SVC-010] 번역 요청.

    콘텐츠 번역을 요청한다.
    """
    raise NotImplementedError("[SVC-010] 기능 구현이 필요합니다.")
