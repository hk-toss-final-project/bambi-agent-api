"""기능 구현 모듈.

SEC-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sec_010(request: FeatureRequest) -> FeatureResult:
    """[SEC-010] Prompt Injection 방어.

    외부 문서의 명령문이 Agent 지시를 변경하지 못하도록 한다.
    """
    raise NotImplementedError("[SEC-010] 기능 구현이 필요합니다.")
