"""기능 구현 모듈.

QUALITY-013, QUALITY-014 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def quality_013(request: FeatureRequest) -> FeatureResult:
    """[QUALITY-013] 품질 미달 재생성.

    품질 기준 미달 시 콘텐츠를 다시 생성한다.
    """
    raise NotImplementedError("[QUALITY-013] 기능 구현이 필요합니다.")


async def quality_014(request: FeatureRequest) -> FeatureResult:
    """[QUALITY-014] 품질 미달 발행 차단.

    최소 품질 기준을 충족하지 못한 콘텐츠의 발행을 차단한다.
    """
    raise NotImplementedError("[QUALITY-014] 기능 구현이 필요합니다.")
