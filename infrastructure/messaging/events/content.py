"""기능 구현 모듈.

EVT-004, EVT-005 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def evt_004(request: FeatureRequest) -> FeatureResult:
    """[EVT-004] Content Ready 이벤트.

    발행 가능한 콘텐츠가 준비되었음을 전달한다.
    """
    raise NotImplementedError("[EVT-004] 기능 구현이 필요합니다.")


async def evt_005(request: FeatureRequest) -> FeatureResult:
    """[EVT-005] Content Generation Failed 이벤트.

    콘텐츠 생성 실패 사실을 전달한다.
    """
    raise NotImplementedError("[EVT-005] 기능 구현이 필요합니다.")
