"""기능 구현 모듈.

PWE-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def pwe_008(request: FeatureRequest) -> FeatureResult:
    """[PWE-008] Vector Namespace 분리.

    사용자별 Vector 검색 범위를 분리한다.
    """
    raise NotImplementedError("[PWE-008] 기능 구현이 필요합니다.")
