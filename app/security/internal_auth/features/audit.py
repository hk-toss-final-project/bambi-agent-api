"""기능 구현 모듈.

AUTH-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def auth_008(request: FeatureRequest) -> FeatureResult:
    """[AUTH-008] 관리자 Audit Context.

    관리자 ID, 변경 사유, Trace 정보를 전달받는다.
    """
    raise NotImplementedError("[AUTH-008] 기능 구현이 필요합니다.")
