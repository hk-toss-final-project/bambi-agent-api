"""기능 구현 모듈.

MCPTOOL-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def mcptool_012(request: FeatureRequest) -> FeatureResult:
    """[MCPTOOL-012] Prompt 테스트.

    관리자 권한으로 Prompt를 테스트한다.
    """
    raise NotImplementedError("[MCPTOOL-012] 기능 구현이 필요합니다.")
