"""기능 구현 모듈.

SVC-001 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def svc_001(request: FeatureRequest) -> FeatureResult:
    """[SVC-001] 사용자 컨텍스트 전달.

    서비스 사용자 설정을 Agent 컨텍스트로 전달한다.
    """
    raise NotImplementedError("[SVC-001] 기능 구현이 필요합니다.")
