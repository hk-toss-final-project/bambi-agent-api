"""기능 구현 모듈.

EXT-004, EXT-005 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ext_004(request: FeatureRequest) -> FeatureResult:
    """[EXT-004] 외부 Global Search API.

    Global Source Pool 검색 기능을 제공한다.
    """
    raise NotImplementedError("[EXT-004] 기능 구현이 필요합니다.")


async def ext_005(request: FeatureRequest) -> FeatureResult:
    """[EXT-005] 외부 Personal Wiki Search API.

    사용자 승인이 있는 개인 Wiki 검색을 제공한다.
    """
    raise NotImplementedError("[EXT-005] 기능 구현이 필요합니다.")
