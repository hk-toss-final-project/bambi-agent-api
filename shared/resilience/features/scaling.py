"""기능 구현 모듈.

NFR-014, NFR-015 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def nfr_014(request: FeatureRequest) -> FeatureResult:
    """[NFR-014] Horizontal Scaling.

    API와 Worker를 수평 확장할 수 있어야 한다.
    """
    raise NotImplementedError("[NFR-014] 기능 구현이 필요합니다.")


async def nfr_015(request: FeatureRequest) -> FeatureResult:
    """[NFR-015] Worker Auto Scaling.

    Queue 적체에 따라 Worker 수를 조정할 수 있어야 한다.
    """
    raise NotImplementedError("[NFR-015] 기능 구현이 필요합니다.")
