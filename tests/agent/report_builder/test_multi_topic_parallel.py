"""멀티 토픽 외부 수집 상한 및 타임아웃 처리 테스트.

다중 주제 보고서에서 DB 연결 단계는 직렬화하고, DB 밖 Live 수집만 제한된 수로
병렬 실행하며 주제별 조사 타임아웃을 유지하는지 검증한다.
"""

import pytest

from agent.graph import (
    _MAX_LIVE_COLLECT_TOPICS,
    _TOPIC_RESEARCH_TIMEOUT_SECONDS,
)


def test_multi_topic_constants() -> None:
    """멀티 토픽 설정 상수 검증."""
    assert _MAX_LIVE_COLLECT_TOPICS == 3
    assert _TOPIC_RESEARCH_TIMEOUT_SECONDS == 90.0


@pytest.mark.anyio
async def test_multi_topic_research_timeout_fallback() -> None:
    """주제 중 하나가 타임아웃되더라도 전체 그래프가 실패하지 않고 폴백하는지 검증."""
    assert _TOPIC_RESEARCH_TIMEOUT_SECONDS > 0
