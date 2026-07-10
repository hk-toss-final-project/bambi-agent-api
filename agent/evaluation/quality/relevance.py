"""기능 구현 모듈.

QUALITY-001 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def quality_001(request: FeatureRequest) -> FeatureResult:
    """[QUALITY-001] 관련성 평가.

    사용자 관심사와 생성 목적의 일치도를 평가한다.
    """
    raise NotImplementedError("[QUALITY-001] 기능 구현이 필요합니다.")
