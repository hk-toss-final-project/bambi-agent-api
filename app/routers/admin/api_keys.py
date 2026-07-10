"""기능 구현 모듈.

ADMIN-022 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def admin_022(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-022] API Key 관리.

    외부 API Key를 발급하고 폐기한다.
    """
    raise NotImplementedError("[ADMIN-022] 기능 구현이 필요합니다.")
