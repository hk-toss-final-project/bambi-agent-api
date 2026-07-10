"""기능 구현 모듈.

NFR-011, NFR-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def nfr_011(request: FeatureRequest) -> FeatureResult:
    """[NFR-011] Outbox Pattern.

    DB 저장과 이벤트 발행의 일관성을 보장한다.
    """
    raise NotImplementedError("[NFR-011] 기능 구현이 필요합니다.")


async def nfr_012(request: FeatureRequest) -> FeatureResult:
    """[NFR-012] Inbox Pattern.

    Consumer의 이벤트 중복 처리를 방지한다.
    """
    raise NotImplementedError("[NFR-012] 기능 구현이 필요합니다.")
