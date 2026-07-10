"""기능 구현 모듈.

TR-007 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def tr_007(request: FeatureRequest) -> FeatureResult:
    """[TR-007] 도메인 용어집 반영.

    기술, 금융 등 분야별 용어를 일관되게 번역한다.
    """
    raise NotImplementedError("[TR-007] 기능 구현이 필요합니다.")
