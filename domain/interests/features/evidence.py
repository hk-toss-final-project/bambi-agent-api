"""기능 구현 모듈.

INT-007 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def int_007(request: FeatureRequest) -> FeatureResult:
    """[INT-007] 관심사 근거 추적.

    관심사를 만든 Wiki 문서와 사용자 행동을 연결한다.
    """
    raise NotImplementedError("[INT-007] 기능 구현이 필요합니다.")
