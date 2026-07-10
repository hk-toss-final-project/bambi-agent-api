"""기능 구현 모듈.

NFR-021 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def nfr_021(request: FeatureRequest) -> FeatureResult:
    """[NFR-021] 비용 제한.

    사용자, 플랜, 기능별 최대 비용을 제한한다.
    """
    raise NotImplementedError("[NFR-021] 기능 구현이 필요합니다.")
