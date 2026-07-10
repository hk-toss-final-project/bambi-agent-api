"""기능 구현 모듈.

GSP-015 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def gsp_015(request: FeatureRequest) -> FeatureResult:
    """[GSP-015] 개인 Wiki 자동 반영 금지.

    수집 데이터를 사용자 선택 없이 개인 Wiki에 반영하지 않는다.
    """
    raise NotImplementedError("[GSP-015] 기능 구현이 필요합니다.")
