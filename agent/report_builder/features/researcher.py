"""자료 조사 에이전트(Researcher).

리포트 근거 자료를 모으는 일을 **LLM이 스스로 판단해** 수행한다. 어떤 도구를
어떤 검색어로 몇 번 부를지 코드가 정하지 않는다 — 도구 목록과 원칙만 주고
LLM이 관찰 결과를 보며 다음 행동을 정한다.

기존 `load_context`는 "풀 검색 → 부족하면 수집"을 고정 순서로 실행했다. 이
모듈은 같은 재료(풀 검색·실시간 수집)를 **도구로 노출**해 LLM이 고르게 한다.
그 결과 토픽어 하나에 묶이지 않고, 관찰에서 발견한 연관 키워드로 검색을
넓힐 수 있다.

판단만 LLM에게 넘기고 **점수 계산·신선도 컷오프는 결정론으로 남긴다** —
도구 안쪽은 기존 `pool_context`·`live_sources` 규칙을 그대로 쓴다.
"""

from __future__ import annotations

import logging
import os
import re
from asyncio import to_thread
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from psycopg import AsyncConnection

from agent.llm.api import ToolCallRecord, ToolSpec, run_tool_loop
from domain.personal_wiki.retrieval.api import prag_003
from infrastructure.persistence.api import (
    load_global_document_freshness,
    set_personal_wiki_scope,
)
from shared.report_models import ReportContextDocument

from .live_sources import collect_live_context
from .pool_context import (
    GLOBAL_NAMESPACE,
    POOL_MIN_DOCUMENTS,
    select_pool_documents,
)

logger = logging.getLogger("agent.report_builder.researcher")

type DictRow = dict[str, Any]

RESEARCH_MAX_ITERATIONS = 5
_OBSERVATION_SNIPPET_CHARS = 160

SYSTEM_PROMPT = (
    "너는 리포트 작성에 쓸 근거 자료를 모으는 조사원이다.\n"
    "도구를 사용해 자료를 모으고, 다 모았으면 무엇을 모았는지 한 문단으로 요약한다.\n"
    "\n"
    "원칙:\n"
    "1. 먼저 search_pool로 이미 모아둔 자료를 확인한다. 비용과 시간이 들지 않는다.\n"
    "2. 주제어 하나로만 찾지 마라. 첫 결과에 주제와 밀접한 용어가 보이면\n"
    "   그 용어로 한두 번 더 search_pool을 불러 자료를 넓힌다.\n"
    f"3. **모은 근거가 {POOL_MIN_DOCUMENTS}건 이상이면 거기서 멈추고 요약한다.**\n"
    "   더 검색하지 말고 collect_live도 부르지 마라. 이미 충분하다.\n"
    f"4. collect_live는 **근거가 {POOL_MIN_DOCUMENTS}건에 못 미칠 때만** 쓴다.\n"
    "   인터넷을 직접 뒤지므로 느리고 비용이 크다. 충분한데 부르면 낭비다.\n"
    "5. 검색어를 바꿨는데 새로 나온 자료가 없으면 그 방향은 접는다.\n"
    "   비슷한 말로 바꿔 가며 같은 검색을 반복하지 마라.\n"
    "6. 주제와 무관한 자료가 나오면 그 검색어는 버리고 다른 검색어를 시도한다.\n"
)


def research_agent_enabled() -> bool:
    """조사원 에이전트를 사용할지 환경변수로 확인한다.

    끄면 기존 고정 경로(풀 검색 → 부족하면 수집)로 되돌아간다. 조사원은 도구
    호출마다 LLM을 부르므로, 비용·지연을 비교하거나 장애 시 즉시 되돌리려면
    스위치가 필요하다. 기본값은 켬이다.
    """
    return os.getenv("RESEARCH_AGENT_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }


@dataclass(frozen=True, slots=True)
class ResearchOutcome:
    """조사 결과로 모인 근거 문서와 실행 기록.

    Attributes:
        documents: 중복 제거된 근거 문서 목록
        calls: LLM이 실행한 도구 호출 기록(어떤 검색어를 왜 골랐는지 추적용)
        notes: LLM이 남긴 조사 요약
        stop_reason: 루프 종료 사유("final" 또는 "max_iterations")
        input_tokens·output_tokens: 조사에 쓴 토큰 (벤치마크 비용 기록용)
    """

    documents: tuple[ReportContextDocument, ...] = ()
    calls: tuple[ToolCallRecord, ...] = ()
    notes: str = ""
    stop_reason: str = "final"
    input_tokens: int = 0
    output_tokens: int = 0


def _document_key(document: ReportContextDocument) -> str:
    """중복 판정에 쓸 문서 식별 키를 만든다."""
    return document.url or f"{document.namespace_key}:{document.document_version_id}"


async def search_stored_documents(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    query: str,
    topic_intent: str = "news",
) -> list[ReportContextDocument]:
    """저장된 자료(개인 Wiki + Global 풀)를 검색해 쓸 만한 문서를 반환한다.

    조사원과 검토자가 함께 쓰는 검색 경계다. 풀 문서는 기존 신선도·점수 컷오프
    (select_pool_documents)를 그대로 적용하고, 개인 Wiki 문서는 그대로 통과시킨다.

    Args:
        connection: 검색에 사용할 DB 연결
        user_id: 검색 Scope 사용자 식별자
        query: 검색어
        topic_intent: 토픽 성격("news"|"evergreen"). 풀 신선도 하한을 정한다.

    Returns:
        개인 Wiki 문서와 컷오프를 통과한 풀 문서 목록
    """
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        hybrid = await prag_003(connection, user_id=user_id, query=query)
        freshness = await load_global_document_freshness(
            connection,
            [
                document.document_version_id
                for document in hybrid
                if document.namespace_key == GLOBAL_NAMESPACE
            ],
        )
    personal = [
        document for document in hybrid if document.namespace_key != GLOBAL_NAMESPACE
    ]
    pool = select_pool_documents(
        hybrid, published_at=freshness, topic_intent=topic_intent
    )
    return [*personal, *pool]


def describe_documents(documents: Sequence[ReportContextDocument]) -> str:
    """도구 실행 결과를 LLM이 판단할 수 있는 관찰 문자열로 만든다.

    제목만 주면 관련성을 판단할 수 없고, 본문 전체를 주면 대화가 폭발한다.
    제목과 앞부분 발췌만 준다.
    """
    if not documents:
        return "결과 없음."
    lines = [f"{len(documents)}건을 찾았다."]
    for index, document in enumerate(documents, start=1):
        snippet = " ".join(document.content.split())[:_OBSERVATION_SNIPPET_CHARS]
        lines.append(f"{index}. {document.title}\n   {snippet}")
    return "\n".join(lines)


class DocumentCollector:
    """도구가 찾아낸 문서를 모으고, 중복 제거와 참조 번호 재부여를 한다.

    **참조 번호를 다시 매기는 이유**: 검색은 호출마다 P1·P2…를 처음부터 새로
    붙인다. 조사원은 검색을 여러 번 하므로 그대로 두면 서로 다른 문서가 같은
    P4를 갖는다. 하류의 `select_generation_context`가 참조 ID로 중복을 걸러
    **뒤에 온 문서를 조용히 버리고**, 인용도 엉뚱한 문서를 가리키게 된다.
    (2026-07-30 실측: 7건을 모았는데 P4가 3건이라 2건이 사라졌다.)
    """

    def __init__(self) -> None:
        """수집 상태를 초기화한다."""
        self._documents: list[ReportContextDocument] = []
        self._seen: set[str] = set()
        self._counters: dict[str, int] = {}

    def _next_reference(self, reference: str) -> str:
        """접두 문자(P/G/L)를 유지한 채 이어지는 번호를 부여한다."""
        match = re.match(r"[A-Za-z]+", reference or "")
        prefix = match.group(0) if match else "P"
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{prefix}{self._counters[prefix]}"

    def add(
        self, documents: Sequence[ReportContextDocument]
    ) -> list[ReportContextDocument]:
        """새 문서만 참조 번호를 다시 매겨 보관하고, 추가된 것을 반환한다."""
        added: list[ReportContextDocument] = []
        for document in documents:
            key = _document_key(document)
            if key in self._seen:
                continue
            self._seen.add(key)
            renumbered = replace(
                document, reference=self._next_reference(document.reference)
            )
            self._documents.append(renumbered)
            added.append(renumbered)
        return added

    @property
    def documents(self) -> tuple[ReportContextDocument, ...]:
        """지금까지 모인 문서를 반환한다."""
        return tuple(self._documents)


def build_research_tools(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    topic_intent: str,
    model: str,
    collector: DocumentCollector,
) -> list[ToolSpec]:
    """조사원이 사용할 도구 목록을 만든다.

    Args:
        connection: 풀·개인 Wiki 검색에 사용할 DB 연결
        user_id: 검색 Scope와 수집 이력에 사용할 사용자 식별자
        topic_intent: 토픽 성격("news"|"evergreen"). 풀 신선도 하한을 정한다.
        model: 실시간 수집 비서가 사용할 모델
        collector: 도구가 찾은 문서를 모을 수집기

    Returns:
        LLM에 노출할 ToolSpec 목록
    """

    async def search_pool(query: str) -> str:
        """저장된 자료(개인 Wiki + Global 풀)에서 검색어로 자료를 찾는다."""
        if not query.strip():
            return "검색어가 비어 있다."
        found = await search_stored_documents(
            connection, user_id=user_id, query=query, topic_intent=topic_intent
        )
        return describe_documents(collector.add(found))

    async def collect_live(keyword: str) -> str:
        """인터넷에서 키워드로 최신 자료를 수집한다(느리고 비용이 든다)."""
        if not keyword.strip():
            return "검색어가 비어 있다."
        documents = await to_thread(
            collect_live_context, keyword, user_id, model=model
        )
        return describe_documents(collector.add(documents))

    keyword_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "찾을 검색어. 주제어 또는 연관 키워드",
            }
        },
        "required": ["query"],
    }
    return [
        ToolSpec(
            name="search_pool",
            description=(
                "이미 저장해 둔 자료(개인 Wiki + 수집해 놓은 뉴스 풀)에서 찾는다. "
                "빠르고 비용이 없으므로 항상 먼저 시도한다."
            ),
            parameters=keyword_schema,
            run=search_pool,
        ),
        ToolSpec(
            name="collect_live",
            description=(
                "인터넷에서 최신 자료를 새로 수집한다. 느리고 비용이 들므로 "
                "search_pool 결과가 없거나 부족할 때만 사용한다."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "수집할 키워드",
                    }
                },
                "required": ["keyword"],
            },
            run=collect_live,
        ),
    ]


async def research_context(
    connection: AsyncConnection[DictRow],
    *,
    topic: str,
    user_id: str,
    topic_intent: str = "news",
    model: str = "gpt-4.1-mini",
    max_iterations: int = RESEARCH_MAX_ITERATIONS,
) -> ResearchOutcome:
    """조사원 에이전트가 도구를 골라 가며 근거 자료를 모은다.

    Args:
        connection: 검색에 사용할 DB 연결
        topic: 리포트 주제
        user_id: 대상 사용자 식별자
        topic_intent: 토픽 성격("news"|"evergreen")
        model: 조사 판단과 수집에 사용할 모델
        max_iterations: 도구 호출 왕복 상한

    Returns:
        모인 근거 문서와 도구 호출 기록
    """
    collector = DocumentCollector()
    tools = build_research_tools(
        connection,
        user_id=user_id,
        topic_intent=topic_intent,
        model=model,
        collector=collector,
    )
    result = await run_tool_loop(
        SYSTEM_PROMPT,
        f"리포트 주제: {topic}\n이 주제로 리포트를 쓸 근거 자료를 모아라.",
        tools,
        model=model,
        max_iterations=max_iterations,
    )
    logger.info(
        "조사 완료: topic=%s 도구호출=%d 문서=%d 종료=%s",
        topic,
        len(result.calls),
        len(collector.documents),
        result.stop_reason,
    )
    return ResearchOutcome(
        documents=collector.documents,
        calls=result.calls,
        notes=result.text,
        stop_reason=result.stop_reason,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )
