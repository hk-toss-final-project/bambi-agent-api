"""기능 구현 모듈.

NFR-001 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def nfr_001(request: FeatureRequest) -> FeatureResult:
    """[NFR-001] Eventual Consistency.

    Service와 Agent 데이터 간 지연된 일관성을 허용한다.
    """
    raise NotImplementedError("[NFR-001] 기능 구현이 필요합니다.")
