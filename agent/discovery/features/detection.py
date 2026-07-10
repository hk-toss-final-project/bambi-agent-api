"""기능 구현 모듈.

DISC-001, DISC-002 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def disc_001(request: FeatureRequest) -> FeatureResult:
    """[DISC-001] 신규 자료 탐지.

    이전 수집 이후 새롭게 추가된 자료를 탐지한다.
    """
    raise NotImplementedError("[DISC-001] 기능 구현이 필요합니다.")


async def disc_002(request: FeatureRequest) -> FeatureResult:
    """[DISC-002] 트렌드 Topic 탐지.

    수집 데이터에서 새롭게 부상하는 주제를 탐지한다.
    """
    raise NotImplementedError("[DISC-002] 기능 구현이 필요합니다.")
