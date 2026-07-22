"""Worker Job 순차 실행 제어 기능과 외부 API Rate Limit Scaffold."""

from collections.abc import Awaitable, Callable, Sequence

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wc_013[ItemT, ResultT](
    items: Sequence[ItemT], processor: Callable[[ItemT], Awaitable[ResultT]]
) -> list[ResultT]:
    """[WC-013] Concurrency 제어.

    작업 유형별 동시 실행 수를 제한한다.
    """
    results: list[ResultT] = []
    for item in items:
        results.append(await processor(item))
    return results


async def wc_014(request: FeatureRequest) -> FeatureResult:
    """[WC-014] 외부 API Rate Limit.

    외부 Source와 Provider의 호출 제한을 준수한다.
    """
    raise NotImplementedError("[WC-014] 기능 구현이 필요합니다.")
