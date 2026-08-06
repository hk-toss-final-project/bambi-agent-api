"""키워드 비서 오케스트레이터.

키워드 하나를 받아 리서치 에이전트(graph)를 실행하고, 웹/엔드포인트가 바로
렌더링할 수 있는 결과 딕셔너리로 묶는 진입점을 제공한다. 수집·선별·중복
제거는 에이전트가 도구로 감싼 결정적 파이프라인(pipeline)이 수행한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent.assistant.features import graph


def assist_daily_agent(
    keyword: str,
    *,
    user_id: str,
    model: str = "gpt-4.1-mini",
    extra_queries: Sequence[str] = (),
    record_history: bool = True,
    include_report: bool = True,
) -> dict[str, object]:
    """리서치 에이전트를 실행해 일간 보고서를 생성한다.

    `assist_daily`와 결과 형태(mode·items·report_markdown·log·errors)는 같되,
    수집 결과가 빈약할 때 에이전트가 검색어를 재구성해 다시 시도한다. 어떤 판단을
    했는지는 agent_trace, 시도한 검색어는 attempts로 함께 반환한다.

    Args:
        keyword: 사용자 관심 토픽
        user_id: 사용자 식별자
        model: 재구성·요약·보고서 생성에 쓸 OpenAI 모델
        extra_queries: 수집에 함께 던질 보조 검색어. **기본은 비어 있다** —
            브리핑(아침 보고서)은 지금까지처럼 키워드 하나로 수집한다. 개인
            Wiki 이웃으로 넓히는 것은 리포트 생성 경로만 켠다
            (report_builder.features.live_sources).
        record_history: 수집·보고 이력을 기록할지. 브리핑은 True(기본),
            리포트 생성처럼 근거만 가져가는 호출은 False로 둔다 — 그래야 리포트
            생성이 사용자의 브리핑에서 같은 소식을 가리지 않는다.
        include_report: 브리핑 Markdown을 생성할지. 근거만 필요하면 False.

    Returns:
        assist_daily 결과 + {agent_trace: [str], attempts: [str]}
    """
    return graph.run_agent(
        keyword,
        user_id,
        model=model,
        extra_queries=extra_queries,
        record_history=record_history,
        include_report=include_report,
    )
