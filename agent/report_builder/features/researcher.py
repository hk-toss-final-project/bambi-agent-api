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
    is_pool_sufficient,
    select_pool_documents,
)

logger = logging.getLogger("agent.report_builder.researcher")

type DictRow = dict[str, Any]

RESEARCH_MAX_ITERATIONS = 5
_OBSERVATION_SNIPPET_CHARS = 160

# 개인 Wiki 문서를 근거로 채택할 점수 하한. 풀 문서(POOL_SCORE_FLOOR)와 같은 취지의
# 절대 하한이지만, 검색 경로가 달라 값을 따로 잰다.
#
# 실측(2026-08-05, mock-clipping-user 46문서 기준):
#
#   관련 있음   0.112 ~ 0.240  ('반도체'→SK하이닉스 0.137, '코스피'→서킷 브레이커 0.240,
#                              '블록체인'→로빈후드 체인 0.112)
#   잡음        0.000          ('요가 스트레칭'·'커피 원두 로스팅' 각 5건 전부)
#
# 개인 Wiki 검색은 매칭이 없어도 문서를 채워 반환하지만 점수를 0으로 정직하게
# 남긴다. 0.05는 잡음(0)의 명백히 위, 관련 최소(0.112)의 절반 아래다.
PERSONAL_SCORE_FLOOR: float = float(os.getenv("PERSONAL_SCORE_FLOOR", "0.05"))

# 조사원에게는 "무엇을 검색할까"만 맡긴다. "몇 건이면 충분한가"는 세는 문제라
# 코드(is_pool_sufficient)가 판정한다 — 2026-07-31 벤치마크에서 LLM에게 셈을
# 맡겼을 때 판단 정확도가 80%에 그쳤고, 프롬프트를 두 번 고쳐도 오류 방향만
# 바뀌었다. 상세는 bench/researcher/results/ 참고.
SYSTEM_PROMPT = (
    "너는 리포트 작성에 쓸 근거 자료를 모으는 조사원이다.\n"
    "search_pool로 자료를 모으고, 다 모았으면 무엇을 모았는지 한 문단으로 요약한다.\n"
    "\n"
    "원칙:\n"
    "1. 주제어로 먼저 검색한다.\n"
    "2. 주제어 하나로만 찾지 마라. 첫 결과에 주제와 밀접한 용어가 보이면\n"
    "   그 용어로 한두 번 더 search_pool을 불러 자료를 넓힌다.\n"
    "3. 검색어를 바꿨는데 새로 나온 자료가 없으면 그 방향은 접는다.\n"
    "   비슷한 말로 바꿔 가며 같은 검색을 반복하지 마라.\n"
    "4. 주제와 무관한 자료가 나오면 그 검색어는 버리고 다른 검색어를 시도한다.\n"
    "5. 더 넓힐 방향이 없으면 그만 찾고 요약한다.\n"
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
    (select_pool_documents)를 적용하고, 개인 Wiki 문서에는 PERSONAL_SCORE_FLOOR를
    적용한다.

    개인 Wiki도 컷오프가 필요하다 — 검색은 매칭이 없어도 문서를 채워 반환하므로,
    거르지 않으면 무관한 주제에서 Wiki 목차 파일(Schema) 청크가 근거로 들어온다
    (2026-08-05 실측: '요가 스트레칭'·'커피 원두 로스팅'이 각각 0.000점 5건을
    돌려줬고, 5건 모두 같은 목차 문서의 청크였다).

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
        document
        for document in hybrid
        if document.namespace_key != GLOBAL_NAMESPACE
        and document.score >= PERSONAL_SCORE_FLOOR
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


def pool_documents_for_decision(
    documents: Sequence[ReportContextDocument],
) -> list[ReportContextDocument]:
    """실시간 수집 여부 판정에 쓸 풀 문서만 문서 단위로 추린다.

    두 가지를 바로잡는다.

    1. **개인 Wiki를 세지 않는다.** 판정이 묻는 것은 "인터넷에 새로 나가야 하는가"
       인데, 어제 저장한 Wiki 문서가 있다고 오늘 소식이 필요 없어지지는 않는다.
       기존 고정 경로(graph.load_context)도 풀 문서만 센다.
    2. **같은 문서의 청크를 1건으로 센다.** Wiki 검색은 청크 단위로 반환하므로
       문서 하나가 5건으로 부풀어 기준(3건)을 넘겨버린다.

    (2026-08-05 실측: '요가 스트레칭'이 목차 문서 1개의 청크 5건으로 "자료 충분"
    판정을 받아 실시간 수집을 건너뛰었다.)

    Args:
        documents: 조사원이 모은 개인·풀 혼합 문서

    Returns:
        문서 단위로 중복을 제거한 풀 문서 목록
    """
    selected: list[ReportContextDocument] = []
    seen: set[str] = set()
    for document in documents:
        if getattr(document, "namespace_key", "") != GLOBAL_NAMESPACE:
            continue
        # 문서 ID가 없으면 URL로, 그것도 없으면 참조 ID로 문서를 구분한다.
        key = (
            str(getattr(document, "document_version_id", "") or "")
            or str(getattr(document, "url", "") or "")
            or document.reference
        )
        if key in seen:
            continue
        seen.add(key)
        selected.append(document)
    return selected


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
    collector: DocumentCollector,
) -> list[ToolSpec]:
    """조사원이 사용할 도구 목록을 만든다.

    **검색 도구 하나만 준다.** 실시간 수집(collect_live)은 도구로 노출하지
    않는다 — 언제 부를지가 "근거가 몇 건인가"에 달린 셈의 문제라, 조사원이
    끝난 뒤 `research_context`가 `is_pool_sufficient`로 판정해 직접 부른다.

    Args:
        connection: 풀·개인 Wiki 검색에 사용할 DB 연결
        user_id: 검색 Scope에 사용할 사용자 식별자
        topic_intent: 토픽 성격("news"|"evergreen"). 풀 신선도 하한을 정한다.
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

    return [
        ToolSpec(
            name="search_pool",
            description=(
                "이미 저장해 둔 자료(개인 Wiki + 수집해 놓은 뉴스 풀)에서 찾는다."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "찾을 검색어. 주제어 또는 연관 키워드",
                    }
                },
                "required": ["query"],
            },
            run=search_pool,
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
    """조사원이 저장된 자료를 훑고, 부족하면 실시간 수집으로 보강한다.

    **역할을 둘로 나눈다.** "무엇을 검색할까"는 LLM이 정하고(연관 키워드 확장),
    "몇 건이면 충분한가"는 `is_pool_sufficient`가 센다. 셈까지 LLM에게 맡겼을
    때 판단 정확도가 80%에 머물렀고, 프롬프트를 두 번 고쳐도 과호출이
    과소호출로 바뀔 뿐이었다(2026-07-31 벤치마크).

    판정 대상은 `pool_documents_for_decision`이 추린 풀 문서뿐이다. 근거로는
    개인 Wiki 문서도 그대로 넘어간다 — 판정에서 빼는 것과 근거에서 빼는 것은
    다른 문제다.

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
        collector=collector,
    )
    result = await run_tool_loop(
        SYSTEM_PROMPT,
        f"리포트 주제: {topic}\n이 주제로 리포트를 쓸 근거 자료를 모아라.",
        tools,
        model=model,
        max_iterations=max_iterations,
    )
    searched = len(collector.documents)
    decision_pool = pool_documents_for_decision(collector.documents)

    # 저장된 자료가 기준에 못 미치면 인터넷에서 보강한다. 실패해도 예외를
    # 올리지 않는다 — 수집이 안 됐다고 지금까지 모은 근거까지 버릴 이유는 없다.
    collected_live = False
    if not is_pool_sufficient(decision_pool):
        collected_live = True
        try:
            live = await to_thread(collect_live_context, topic, user_id, model=model)
            collector.add(live)
        except Exception:
            logger.exception("실시간 수집에 실패해 저장된 자료만 사용합니다.")

    logger.info(
        "조사 완료: topic=%s 도구호출=%d 저장자료=%d 판정풀=%d 실시간수집=%s 최종=%d 종료=%s",
        topic,
        len(result.calls),
        searched,
        len(decision_pool),
        "수행" if collected_live else "생략",
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
