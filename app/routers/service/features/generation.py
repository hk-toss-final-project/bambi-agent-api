"""기능 구현 모듈.

SVC-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def svc_008(request: FeatureRequest) -> FeatureResult:
    """[SVC-008] 콘텐츠 생성 요청.

    밤비의 콘텐츠 생성을 요청한다.
    """
    raise NotImplementedError("[SVC-008] 기능 구현이 필요합니다.")
