"""기능 구현 모듈.

REC-016 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def rec_016(request: FeatureRequest) -> FeatureResult:
    """[REC-016] 추천 완료 이벤트.

    추천 결과 준비 완료를 이벤트로 발행한다.
    """
    raise NotImplementedError("[REC-016] 기능 구현이 필요합니다.")
