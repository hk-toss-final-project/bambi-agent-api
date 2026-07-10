"""기능 구현 모듈.

MCPTOOL-001, MCPTOOL-002, MCPTOOL-003 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def mcptool_001(request: FeatureRequest) -> FeatureResult:
    """[MCPTOOL-001] Personal Wiki 검색.

    승인된 사용자의 개인 Wiki를 검색한다.
    """
    raise NotImplementedError("[MCPTOOL-001] 기능 구현이 필요합니다.")


async def mcptool_002(request: FeatureRequest) -> FeatureResult:
    """[MCPTOOL-002] Personal Wiki 문서 조회.

    개인 Wiki의 특정 문서를 조회한다.
    """
    raise NotImplementedError("[MCPTOOL-002] 기능 구현이 필요합니다.")


async def mcptool_003(request: FeatureRequest) -> FeatureResult:
    """[MCPTOOL-003] Personal Wiki Source 추가.

    사용자 승인 하에 Wiki Source를 추가한다.
    """
    raise NotImplementedError("[MCPTOOL-003] 기능 구현이 필요합니다.")
