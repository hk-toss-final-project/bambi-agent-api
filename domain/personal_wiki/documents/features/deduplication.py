"""기능 구현 모듈.

PWIKI-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def pwiki_008(request: FeatureRequest) -> FeatureResult:
    """[PWIKI-008] Wiki 문서 중복 제거.

    동일하거나 유사한 개인 Wiki 문서를 중복 제거한다.
    """
    raise NotImplementedError("[PWIKI-008] 기능 구현이 필요합니다.")
