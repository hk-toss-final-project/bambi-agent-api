"""기능 구현 모듈.

EXT-009 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ext_009(request: FeatureRequest) -> FeatureResult:
    """[EXT-009] 외부 Webhook Callback.

    작업 완료 결과를 외부 시스템에 전달한다.
    """
    raise NotImplementedError("[EXT-009] 기능 구현이 필요합니다.")
