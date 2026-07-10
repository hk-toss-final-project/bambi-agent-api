"""기능 구현 모듈.

NFR-002 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def nfr_002(request: FeatureRequest) -> FeatureResult:
    """[NFR-002] Idempotency.

    동일 요청과 이벤트의 중복 처리에도 결과를 안정적으로 유지한다.
    """
    raise NotImplementedError("[NFR-002] 기능 구현이 필요합니다.")
