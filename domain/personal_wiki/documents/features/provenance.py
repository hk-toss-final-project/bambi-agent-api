"""기능 구현 모듈.

PWIKI-007 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def pwiki_007(request: FeatureRequest) -> FeatureResult:
    """[PWIKI-007] Wiki 문서 출처 추적.

    클리핑, URL, 위키마킹 등 문서 유입 경로를 기록한다.
    """
    raise NotImplementedError("[PWIKI-007] 기능 구현이 필요합니다.")
