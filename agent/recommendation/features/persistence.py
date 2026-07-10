"""기능 구현 모듈.

REC-015 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def rec_015(request: FeatureRequest) -> FeatureResult:
    """[REC-015] 추천 후보 저장.

    추천 계산 결과를 agent-db에 저장한다.
    """
    raise NotImplementedError("[REC-015] 기능 구현이 필요합니다.")
