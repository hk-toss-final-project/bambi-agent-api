"""기능 구현 모듈.

RET-009, RET-010, RET-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ret_009(request: FeatureRequest) -> FeatureResult:
    """[RET-009] Personal Wiki 검색 범위.

    개인 Wiki 검색 깊이와 범위를 설정한다.
    """
    raise NotImplementedError("[RET-009] 기능 구현이 필요합니다.")


async def ret_010(request: FeatureRequest) -> FeatureResult:
    """[RET-010] Global Source 검색 범위.

    Global Source 검색 깊이와 범위를 설정한다.
    """
    raise NotImplementedError("[RET-010] 기능 구현이 필요합니다.")


async def ret_011(request: FeatureRequest) -> FeatureResult:
    """[RET-011] 플랜별 Retrieval 정책.

    무료와 유료 플랜의 검색 범위를 다르게 설정한다.
    """
    raise NotImplementedError("[RET-011] 기능 구현이 필요합니다.")
