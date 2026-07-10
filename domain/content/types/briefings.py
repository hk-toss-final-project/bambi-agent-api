"""기능 구현 모듈.

CTYPE-007, CTYPE-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ctype_007(request: FeatureRequest) -> FeatureResult:
    """[CTYPE-007] 일간 브리핑.

    사용자 관심사에 대한 일간 업데이트를 생성한다.
    """
    raise NotImplementedError("[CTYPE-007] 기능 구현이 필요합니다.")


async def ctype_008(request: FeatureRequest) -> FeatureResult:
    """[CTYPE-008] 주간 리포트.

    일주일간의 주요 변화와 자료를 정리한다.
    """
    raise NotImplementedError("[CTYPE-008] 기능 구현이 필요합니다.")
