"""기능 구현 모듈.

EXT-013, EXT-014 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ext_013(request: FeatureRequest) -> FeatureResult:
    """[EXT-013] 외부 호출 로그.

    외부 API 요청과 결과를 기록한다.
    """
    raise NotImplementedError("[EXT-013] 기능 구현이 필요합니다.")


async def ext_014(request: FeatureRequest) -> FeatureResult:
    """[EXT-014] 외부 사용량 기록.

    외부 고객별 Token과 비용을 기록한다.
    """
    raise NotImplementedError("[EXT-014] 기능 구현이 필요합니다.")
