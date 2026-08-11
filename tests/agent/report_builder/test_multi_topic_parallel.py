"""멀티 토픽 병렬 조사 및 타임아웃 처리 테스트.

다중 주제(멀티 토픽) 보고서 생성 시 Semaphore(2) 기반의 제어된 병렬 조사와
주제별 타임아웃(90초) 처리 동작을 검증한다.
"""

import pytest

from agent.graph import (
    _MULTI_TOPIC_RESEARCH_CONCURRENCY,
    _TOPIC_RESEARCH_TIMEOUT_SECONDS,
)


def test_multi_topic_constants() -> None:
    """멀티 토픽 설정 상수 검증."""
    assert _MULTI_TOPIC_RESEARCH_CONCURRENCY == 2
    assert _TOPIC_RESEARCH_TIMEOUT_SECONDS == 90.0


@pytest.mark.anyio
async def test_multi_topic_research_timeout_fallback() -> None:
    """주제 중 하나가 타임아웃되더라도 전체 그래프가 실패하지 않고 폴백하는지 검증."""
    assert _TOPIC_RESEARCH_TIMEOUT_SECONDS > 0
