"""기능 구현 모듈.

WBA-001, WBA-002 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def wba_001(request: FeatureRequest) -> FeatureResult:
    """[WBA-001] Incremental Wiki Build.

    새로 추가된 사용자 데이터만 개인 Wiki에 반영한다.
    """
    raise NotImplementedError("[WBA-001] 기능 구현이 필요합니다.")


async def wba_002(request: FeatureRequest) -> FeatureResult:
    """[WBA-002] Full Wiki Rebuild.

    전체 개인 Wiki를 재분류하고 재구성한다.
    """
    raise NotImplementedError("[WBA-002] 기능 구현이 필요합니다.")
