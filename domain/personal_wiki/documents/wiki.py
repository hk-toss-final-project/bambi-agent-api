"""기능 구현 모듈.

PWIKI-001 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def pwiki_001(request: FeatureRequest) -> FeatureResult:
    """[PWIKI-001] 개인 Wiki 생성.

    사용자별 개인 LLM Wiki 영역을 생성한다.
    """
    raise NotImplementedError("[PWIKI-001] 기능 구현이 필요합니다.")
