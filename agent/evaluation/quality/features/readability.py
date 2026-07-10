"""기능 구현 모듈.

QUALITY-007, QUALITY-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def quality_007(request: FeatureRequest) -> FeatureResult:
    """[QUALITY-007] 가독성 평가.

    문장과 구조가 읽기 쉬운지 평가한다.
    """
    raise NotImplementedError("[QUALITY-007] 기능 구현이 필요합니다.")


async def quality_008(request: FeatureRequest) -> FeatureResult:
    """[QUALITY-008] 완성도 평가.

    콘텐츠 구조와 내용이 완결되었는지 평가한다.
    """
    raise NotImplementedError("[QUALITY-008] 기능 구현이 필요합니다.")
