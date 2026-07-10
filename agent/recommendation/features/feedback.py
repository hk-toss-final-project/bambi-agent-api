"""기능 구현 모듈.

REC-017 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def rec_017(request: FeatureRequest) -> FeatureResult:
    """[REC-017] 사용자 피드백 반영.

    추천 결과에 대한 사용자 반응을 학습 신호로 반영한다.
    """
    raise NotImplementedError("[REC-017] 기능 구현이 필요합니다.")
