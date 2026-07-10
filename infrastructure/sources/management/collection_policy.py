"""기능 구현 모듈.

GS-007, GS-008, GS-009, GS-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def gs_007(request: FeatureRequest) -> FeatureResult:
    """[GS-007] 수집 주기 설정.

    Source별 수집 실행 주기를 설정한다.
    """
    raise NotImplementedError("[GS-007] 기능 구현이 필요합니다.")


async def gs_008(request: FeatureRequest) -> FeatureResult:
    """[GS-008] 수집 키워드 설정.

    검색 API와 Source별 수집 키워드를 설정한다.
    """
    raise NotImplementedError("[GS-008] 기능 구현이 필요합니다.")


async def gs_009(request: FeatureRequest) -> FeatureResult:
    """[GS-009] 수집 언어 설정.

    수집할 콘텐츠 언어를 설정한다.
    """
    raise NotImplementedError("[GS-009] 기능 구현이 필요합니다.")


async def gs_010(request: FeatureRequest) -> FeatureResult:
    """[GS-010] 수집 카테고리 설정.

    수집할 주제와 카테고리를 설정한다.
    """
    raise NotImplementedError("[GS-010] 기능 구현이 필요합니다.")
