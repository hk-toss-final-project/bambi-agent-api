"""기능 구현 모듈.

SUM-005, SUM-006, SUM-007 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sum_005(request: FeatureRequest) -> FeatureResult:
    """[SUM-005] 한 줄 요약.

    콘텐츠의 핵심을 한 줄로 표현한다.
    """
    raise NotImplementedError("[SUM-005] 기능 구현이 필요합니다.")


async def sum_006(request: FeatureRequest) -> FeatureResult:
    """[SUM-006] 카드 요약.

    피드 카드에 사용할 짧은 설명을 생성한다.
    """
    raise NotImplementedError("[SUM-006] 기능 구현이 필요합니다.")


async def sum_007(request: FeatureRequest) -> FeatureResult:
    """[SUM-007] 상세 요약.

    배경과 맥락을 포함한 상세 요약을 생성한다.
    """
    raise NotImplementedError("[SUM-007] 기능 구현이 필요합니다.")
