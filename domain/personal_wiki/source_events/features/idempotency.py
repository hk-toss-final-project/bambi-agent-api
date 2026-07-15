"""기능 구현 모듈.

WSE-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wse_011(request: FeatureRequest) -> FeatureResult:
    """[WSE-011] 이벤트 중복 처리 방지.

    동일 사용자 이벤트의 중복 처리를 방지한다.
    """
    raise NotImplementedError("[WSE-011] 기능 구현이 필요합니다.")
