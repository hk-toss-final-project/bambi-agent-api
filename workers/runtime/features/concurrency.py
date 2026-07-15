"""기능 구현 모듈.

WC-013, WC-014 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wc_013(request: FeatureRequest) -> FeatureResult:
    """[WC-013] Concurrency 제어.

    작업 유형별 동시 실행 수를 제한한다.
    """
    raise NotImplementedError("[WC-013] 기능 구현이 필요합니다.")


async def wc_014(request: FeatureRequest) -> FeatureResult:
    """[WC-014] 외부 API Rate Limit.

    외부 Source와 Provider의 호출 제한을 준수한다.
    """
    raise NotImplementedError("[WC-014] 기능 구현이 필요합니다.")
