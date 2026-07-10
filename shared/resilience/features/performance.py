"""기능 구현 모듈.

NFR-022 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def nfr_022(request: FeatureRequest) -> FeatureResult:
    """[NFR-022] 성능 모니터링.

    API와 Worker의 처리 시간과 처리량을 지속적으로 측정한다.
    """
    raise NotImplementedError("[NFR-022] 기능 구현이 필요합니다.")
