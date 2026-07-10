"""기능 구현 모듈.

GSP-014 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def gsp_014(request: FeatureRequest) -> FeatureResult:
    """[GSP-014] 오래된 데이터 보존 정책.

    수집 데이터의 보존과 만료 정책을 적용한다.
    """
    raise NotImplementedError("[GSP-014] 기능 구현이 필요합니다.")
