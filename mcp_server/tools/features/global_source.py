"""기능 구현 모듈.

MCPTOOL-004, MCPTOOL-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def mcptool_004(request: FeatureRequest) -> FeatureResult:
    """[MCPTOOL-004] Global Source 검색.

    공용 Global Source Pool을 검색한다.
    """
    raise NotImplementedError("[MCPTOOL-004] 기능 구현이 필요합니다.")


async def mcptool_011(request: FeatureRequest) -> FeatureResult:
    """[MCPTOOL-011] Global Source 수동 수집.

    권한이 있는 사용자가 Source 수집을 실행한다.
    """
    raise NotImplementedError("[MCPTOOL-011] 기능 구현이 필요합니다.")
