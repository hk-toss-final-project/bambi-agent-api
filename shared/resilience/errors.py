"""기능 구현 모듈.

NFR-009, NFR-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def nfr_009(request: FeatureRequest) -> FeatureResult:
    """[NFR-009] 오류 유형 분류.

    재시도 가능한 오류와 불가능한 오류를 구분한다.
    """
    raise NotImplementedError("[NFR-009] 기능 구현이 필요합니다.")


async def nfr_010(request: FeatureRequest) -> FeatureResult:
    """[NFR-010] Dead Letter 처리.

    반복 실패 작업과 이벤트를 격리한다.
    """
    raise NotImplementedError("[NFR-010] 기능 구현이 필요합니다.")
