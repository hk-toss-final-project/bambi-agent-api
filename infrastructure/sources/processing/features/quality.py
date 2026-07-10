"""기능 구현 모듈.

GSP-007 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def gsp_007(request: FeatureRequest) -> FeatureResult:
    """[GSP-007] 문서 품질 필터링.

    스팸, 빈 문서, 깨진 콘텐츠를 제외한다.
    """
    raise NotImplementedError("[GSP-007] 기능 구현이 필요합니다.")
