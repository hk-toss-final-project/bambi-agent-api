"""기능 구현 모듈.

PWIKI-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def pwiki_010(request: FeatureRequest) -> FeatureResult:
    """[PWIKI-010] Wiki 문서 요약.

    긴 문서를 개인 Wiki용 요약 문서로 구성한다.
    """
    raise NotImplementedError("[PWIKI-010] 기능 구현이 필요합니다.")
