"""기능 구현 모듈.

PRAG-005 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def prag_005(request: FeatureRequest) -> FeatureResult:
    """[PRAG-005] 사용자 관심사 기반 검색.

    관심사 프로필을 검색 조건에 반영한다.
    """
    raise NotImplementedError("[PRAG-005] 기능 구현이 필요합니다.")
