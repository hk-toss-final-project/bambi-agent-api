"""Worker Job 동시 실행 제어 기능과 외부 API Rate Limit Scaffold."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wc_013[ItemT, ResultT](
    items: Sequence[ItemT],
    processor: Callable[[ItemT], Awaitable[ResultT]],
    *,
    max_concurrency: int = 1,
) -> list[ResultT]:
    """[WC-013] Concurrency 제어.

    작업 유형별 동시 실행 수를 제한한다.
    """
    if max_concurrency < 1:
        raise ValueError("WC-013 max_concurrency는 1 이상이어야 합니다.")
    semaphore = asyncio.Semaphore(max_concurrency)

    async def run(item: ItemT) -> ResultT:
        """Semaphore 안에서 Item 하나를 실행한다."""
        async with semaphore:
            return await processor(item)

    return list(await asyncio.gather(*(run(item) for item in items)))


async def wc_014(request: FeatureRequest) -> FeatureResult:
    """[WC-014] 외부 API Rate Limit.

    외부 Source와 Provider의 호출 제한을 준수한다.
    """
    raise NotImplementedError("[WC-014] 기능 구현이 필요합니다.")
