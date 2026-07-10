"""기능 구현 모듈.

PRAG-006 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def prag_006(request: FeatureRequest) -> FeatureResult:
    """[PRAG-006] 개인 Wiki Context 구성.

    LLM 입력에 사용할 개인 Wiki Context를 구성한다.
    """
    raise NotImplementedError("[PRAG-006] 기능 구현이 필요합니다.")
