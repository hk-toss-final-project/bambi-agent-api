"""WC-013 실제 작업 동시성 제한을 검증한다."""

import asyncio

import pytest

from workers.runtime.features.concurrency import wc_013


def test_wc_013_limits_concurrency_and_preserves_result_order() -> None:
    """최대 실행 수를 넘지 않으면서 입력 순서대로 결과를 반환한다."""
    active = 0
    peak = 0

    async def process(item: int) -> int:
        """활성 실행 수를 기록하고 입력을 두 배로 반환한다."""
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return item * 2

    results = asyncio.run(wc_013([1, 2, 3, 4], process, max_concurrency=2))

    assert results == [2, 4, 6, 8]
    assert peak == 2


def test_wc_013_rejects_invalid_concurrency() -> None:
    """0 이하 동시성은 실행 전에 거부한다."""
    async def process(item: int) -> int:
        """입력을 그대로 반환한다."""
        return item

    with pytest.raises(ValueError, match="max_concurrency"):
        asyncio.run(wc_013([1], process, max_concurrency=0))
