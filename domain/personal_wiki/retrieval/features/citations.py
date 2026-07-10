"""기능 구현 모듈.

PRAG-007 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def prag_007(request: FeatureRequest) -> FeatureResult:
    """[PRAG-007] Citation 연결.

    생성 결과와 참조한 개인 Wiki 문서를 연결한다.
    """
    raise NotImplementedError("[PRAG-007] 기능 구현이 필요합니다.")
