"""기능 구현 모듈.

SW-007, SW-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sw_007(request: FeatureRequest) -> FeatureResult:
    """[SW-007] service-db 콘텐츠 Upsert.

    콘텐츠 발행본을 service-db에 저장하거나 갱신한다.
    """
    raise NotImplementedError("[SW-007] 기능 구현이 필요합니다.")


async def sw_008(request: FeatureRequest) -> FeatureResult:
    """[SW-008] service-db 피드 Upsert.

    발행 콘텐츠를 사용자 피드에 반영한다.
    """
    raise NotImplementedError("[SW-008] 기능 구현이 필요합니다.")
