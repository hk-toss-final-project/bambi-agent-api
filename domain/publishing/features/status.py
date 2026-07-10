"""기능 구현 모듈.

PUB-004, PUB-005, PUB-006 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def pub_004(request: FeatureRequest) -> FeatureResult:
    """[PUB-004] 발행 상태 관리.

    발행 대기, 발행 완료, 실패 상태를 관리한다.
    """
    raise NotImplementedError("[PUB-004] 기능 구현이 필요합니다.")


async def pub_005(request: FeatureRequest) -> FeatureResult:
    """[PUB-005] 발행 완료 처리.

    Service Worker의 완료 응답을 반영한다.
    """
    raise NotImplementedError("[PUB-005] 기능 구현이 필요합니다.")


async def pub_006(request: FeatureRequest) -> FeatureResult:
    """[PUB-006] 발행 실패 처리.

    발행 실패 사유와 재시도 상태를 기록한다.
    """
    raise NotImplementedError("[PUB-006] 기능 구현이 필요합니다.")
