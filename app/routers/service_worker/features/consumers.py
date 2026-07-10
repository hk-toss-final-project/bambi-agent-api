"""기능 구현 모듈.

SW-001, SW-002, SW-003 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sw_001(request: FeatureRequest) -> FeatureResult:
    """[SW-001] Content Ready 이벤트 수신.

    발행 가능한 콘텐츠 이벤트를 소비한다.
    """
    raise NotImplementedError("[SW-001] 기능 구현이 필요합니다.")


async def sw_002(request: FeatureRequest) -> FeatureResult:
    """[SW-002] Recommendation Ready 이벤트 수신.

    추천 결과 이벤트를 소비한다.
    """
    raise NotImplementedError("[SW-002] 기능 구현이 필요합니다.")


async def sw_003(request: FeatureRequest) -> FeatureResult:
    """[SW-003] Image Asset Ready 이벤트 수신.

    이미지 생성 완료 이벤트를 소비한다.
    """
    raise NotImplementedError("[SW-003] 기능 구현이 필요합니다.")
