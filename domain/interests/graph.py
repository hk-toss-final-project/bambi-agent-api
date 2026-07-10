"""기능 구현 모듈.

INT-003, INT-004 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def int_003(request: FeatureRequest) -> FeatureResult:
    """[INT-003] 관심사 계층 구성.

    상위 관심사와 세부 관심사 구조를 구성한다.
    """
    raise NotImplementedError("[INT-003] 기능 구현이 필요합니다.")


async def int_004(request: FeatureRequest) -> FeatureResult:
    """[INT-004] 관심사 간 관계 구성.

    서로 관련된 관심사 간 연결 관계를 생성한다.
    """
    raise NotImplementedError("[INT-004] 기능 구현이 필요합니다.")
