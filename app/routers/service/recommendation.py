"""기능 구현 모듈.

SVC-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def svc_011(request: FeatureRequest) -> FeatureResult:
    """[SVC-011] 추천 요청.

    사용자별 추천 생성을 요청한다.
    """
    raise NotImplementedError("[SVC-011] 기능 구현이 필요합니다.")
