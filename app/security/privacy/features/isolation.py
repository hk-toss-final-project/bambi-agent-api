"""기능 구현 모듈.

SEC-003, SEC-004 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sec_003(request: FeatureRequest) -> FeatureResult:
    """[SEC-003] 사용자 데이터 격리.

    사용자별 Personal Wiki와 Vector 데이터를 격리한다.
    """
    raise NotImplementedError("[SEC-003] 기능 구현이 필요합니다.")


async def sec_004(request: FeatureRequest) -> FeatureResult:
    """[SEC-004] Personal Wiki 접근 제어.

    사용자 본인과 승인된 주체만 접근하도록 한다.
    """
    raise NotImplementedError("[SEC-004] 기능 구현이 필요합니다.")
