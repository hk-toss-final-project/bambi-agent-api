"""기능 구현 모듈.

ADMIN-023 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def admin_023(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-023] Agent 로그 조회.

    생성, 검색, 수집 로그를 조회한다.
    """
    raise NotImplementedError("[ADMIN-023] 기능 구현이 필요합니다.")
