"""기능 구현 모듈.

PWIKI-003 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def pwiki_003(request: FeatureRequest) -> FeatureResult:
    """[PWIKI-003] 개인 Wiki 문서 조회.

    사용자의 Wiki 문서 목록과 상세 내용을 조회한다.
    """
    raise NotImplementedError("[PWIKI-003] 기능 구현이 필요합니다.")
