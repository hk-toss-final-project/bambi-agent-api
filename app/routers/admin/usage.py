"""기능 구현 모듈.

ADMIN-020, ADMIN-021 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def admin_020(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-020] LLM 사용량 조회.

    모델별 Token 사용량을 조회한다.
    """
    raise NotImplementedError("[ADMIN-020] 기능 구현이 필요합니다.")


async def admin_021(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-021] LLM 비용 조회.

    Provider와 기능별 비용을 조회한다.
    """
    raise NotImplementedError("[ADMIN-021] 기능 구현이 필요합니다.")
