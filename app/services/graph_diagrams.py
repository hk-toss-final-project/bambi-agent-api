"""에이전트 LangGraph 구조를 Mermaid 다이어그램 정의로 추출하는 서비스.

개발용 그래프 시각화 페이지(/dev/graphs)가 사용한다. 각 그래프를 구조 추출
목적으로만 빌드해 LangGraph 내장 `draw_mermaid()`로 정의 텍스트를 뽑는다.
그래프 구조는 코드로 고정돼 있으므로 프로세스당 1회만 추출해 재사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from agent.assistant.api import build_assistant_graph
from agent.graph import build_personal_wiki_graph, build_report_generation_graph


@dataclass(frozen=True, slots=True)
class GraphDiagram:
    """시각화 페이지에 표시할 그래프 하나의 정보."""

    slug: str
    title: str
    description: str
    mermaid: str


def _mermaid_of(compiled: Any) -> str:
    """컴파일된 LangGraph에서 Mermaid 정의 텍스트를 추출한다."""
    return compiled.get_graph().draw_mermaid()


@lru_cache(maxsize=1)
def list_graph_diagrams() -> tuple[GraphDiagram, ...]:
    """세 에이전트 그래프의 Mermaid 정의를 추출해 반환한다.

    Wiki·Report 그래프 빌더는 DB 연결을 인자로 받지만 빌드 시점에는 연결을
    사용하지 않고 노드 클로저만 구성하므로, 구조 추출에는 None을 넘긴다.
    이 전제는 tests/app/test_graph_diagrams.py가 회귀를 감지한다.
    """
    return (
        GraphDiagram(
            slug="personal-wiki",
            title="Personal Wiki Build",
            description=(
                "원본 조회(load_source) → LLM 분류(classify) → 반영 계획(plan) → "
                "문서·Chunk 저장(persist) → Job 결과 조립(finalize)"
            ),
            mermaid=_mermaid_of(build_personal_wiki_graph(None)),
        ),
        GraphDiagram(
            slug="report-generation",
            title="Report Builder Generation",
            description=(
                "개인 Wiki·실시간 자료 검색(load_context) → 콘텐츠 생성(generate) → "
                "Citation·Snapshot 저장(persist)"
            ),
            mermaid=_mermaid_of(build_report_generation_graph(None)),
        ),
        GraphDiagram(
            slug="assistant",
            title="키워드 비서 리서치 에이전트",
            description=(
                "검색어 초기화(plan) → 수집·선별(select) → 결과가 빈약하면 "
                "검색어 재구성(reformulate) 후 재시도 → 보고서 작성(write_report)"
            ),
            mermaid=_mermaid_of(build_assistant_graph()),
        ),
    )


def get_graph_diagram(slug: str) -> GraphDiagram | None:
    """slug에 해당하는 그래프 다이어그램을 반환한다. 없으면 None."""
    for diagram in list_graph_diagrams():
        if diagram.slug == slug:
            return diagram
    return None
