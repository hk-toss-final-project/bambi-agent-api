"""기능 구현 모듈.

PWIKI-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def pwiki_011(request: FeatureRequest) -> FeatureResult:
    """[PWIKI-011] Wiki 문서 정규화.

    문서 형식과 메타 정보를 공통 구조로 변환한다.
    """
    raise NotImplementedError("[PWIKI-011] 기능 구현이 필요합니다.")
