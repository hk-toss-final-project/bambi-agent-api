"""리포트 초안을 검증하는 검토자 에이전트(Critic).

`quality.py`의 무료 코드 검사는 글자 수와 인용 **개수**만 센다. 본문이
"코스피는 시가총액 방식으로 산출됩니다[P4]"라고 썼을 때 **P4 문서에 정말 그
내용이 있는지**는 확인하지 못한다. 이 모듈이 그 2단계를 담당한다.

핵심은 검토자에게 **초안과 근거 목록(제목)만** 주고 원문은 주지 않는 것이다.
확인하려면 `get_source`로 직접 꺼내야 하므로, 어떤 인용을 몇 개나 대조할지
검토자가 스스로 정하게 된다. 빠뜨린 사실을 찾을 때는 `search_pool`로 저장된
자료를 다시 뒤진다 — 초안만 읽어서는 "무엇이 없는지"를 알 수 없기 때문이다.

**실패하면 통과로 처리한다.** 검토는 품질을 높이는 장치지 발행을 막는 관문이
아니다. 검토자가 죽었다고 리포트가 안 나가면 안 된다.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from psycopg import AsyncConnection

from agent.llm.api import ToolCallRecord, ToolSpec, run_tool_loop, strip_json_fence
from shared.report_models import GeneratedReportContent, ReportContextDocument

from .researcher import describe_documents, search_stored_documents

logger = logging.getLogger("agent.report_builder.critic")

type DictRow = dict[str, Any]

CRITIC_MAX_ITERATIONS = 6
_SOURCE_MAX_CHARS = 2000

PASS = "pass"
REVISE = "revise"
UNAVAILABLE = "unavailable"

SYSTEM_PROMPT = (
    "너는 리포트 초안의 사실관계를 검증하는 검토자다.\n"
    "\n"
    "확인할 것은 두 가지다.\n"
    "1. 초안이 인용한 내용이 실제 근거 원문에 있는가\n"
    "2. 주제상 반드시 들어가야 할 사실이 빠지지 않았는가\n"
    "\n"
    "도구:\n"
    "- get_source(reference): 근거 원문을 읽는다. 초안에는 원문이 없으므로\n"
    "  대조하려면 반드시 이 도구를 써야 한다.\n"
    "- search_pool(query): 저장된 자료를 검색한다. 빠진 사실이 있는지 확인할 때 쓴다.\n"
    "\n"
    "원칙:\n"
    "1. 인용을 최소 2개는 get_source로 대조한 뒤에 판정한다.\n"
    "2. 원문에 없는 내용을 인용한 것처럼 쓴 곳이 있으면 revise다.\n"
    "3. 빠진 사실을 지적하려면 search_pool로 그 자료가 실제로 있는지 먼저 확인한다.\n"
    "   추측으로 '이것도 다뤄야 한다'고 지적하지 않는다.\n"
    "4. 문체·길이·구성은 지적하지 않는다. 사실관계만 본다.\n"
    "5. 문제를 못 찾았으면 pass다. 굳이 흠을 만들지 않는다.\n"
    "\n"
    "확인이 끝나면 JSON 객체 하나로만 답한다.\n"
    '{"verdict":"pass" 또는 "revise",'
    '"problem":"무엇이 왜 문제인지",'
    '"correction":"다시 쓸 때 줄 구체적 지시"}\n'
)


def critic_enabled() -> bool:
    """검토자 에이전트를 사용할지 환경변수로 확인한다.

    끄면 무료 코드 검사(quality.py)만으로 발행한다. 검토는 리포트당 LLM 호출을
    늘리므로 비용을 비교하거나 장애 시 즉시 되돌릴 스위치가 필요하다.
    """
    return os.getenv("CRITIC_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }


@dataclass(frozen=True, slots=True)
class CriticVerdict:
    """검토 결과.

    Attributes:
        outcome: "pass"(문제 없음) · "revise"(재작성 필요) · "unavailable"(검토 불가)
        should_regenerate: 재작성이 필요한지
        problem: 검토자가 지적한 문제 (통과면 빈 문자열)
        correction: 재작성 시 프롬프트에 덧붙일 교정 지시
        calls: 검토자가 실행한 도구 호출 기록
        input_tokens·output_tokens: 검토에 쓴 토큰 (벤치마크 비용 기록용)
    """

    outcome: str = PASS
    should_regenerate: bool = False
    problem: str = ""
    correction: str = ""
    calls: tuple[ToolCallRecord, ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0


def _reference_index(
    contexts: Sequence[ReportContextDocument],
) -> dict[str, ReportContextDocument]:
    """참조 ID로 근거 문서를 찾을 수 있게 색인한다.

    참조 ID가 없는 형태(테스트 더미 등)는 건너뛴다 — load_context·
    select_generation_context와 같은 관용 규칙이다. 근거 하나가 이상하다고
    검토 전체를 실패시키지 않는다.
    """
    index: dict[str, ReportContextDocument] = {}
    for document in contexts:
        reference = str(getattr(document, "reference", "") or "")
        if reference:
            index[reference] = document
    return index


def _draft_prompt(
    content: GeneratedReportContent, contexts: Sequence[ReportContextDocument]
) -> str:
    """검토자에게 줄 초안과 근거 목록을 만든다.

    근거는 **제목만** 넣는다. 원문까지 주면 get_source를 쓸 이유가 없어져
    검토자가 도구 없이 훑고 넘어가기 때문이다.
    """
    catalog = "\n".join(
        f"- {reference}: {getattr(document, 'title', '')}"
        for reference, document in _reference_index(contexts).items()
    )
    return (
        f"제목: {content.title}\n"
        f"요약: {content.summary}\n"
        f"본문:\n{content.body}\n\n"
        f"인용 가능한 근거 목록(원문은 get_source로 확인):\n{catalog or '- (없음)'}\n"
    )


def build_critic_tools(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    contexts: Sequence[ReportContextDocument],
    topic_intent: str,
) -> list[ToolSpec]:
    """검토자가 사용할 도구 목록을 만든다.

    Args:
        connection: 추가 검색에 사용할 DB 연결
        user_id: 검색 Scope 사용자 식별자
        contexts: 생성에 사용한 근거 문서 (get_source의 원본)
        topic_intent: 토픽 성격("news"|"evergreen")

    Returns:
        LLM에 노출할 ToolSpec 목록
    """
    by_reference = _reference_index(contexts)

    def get_source(reference: str) -> str:
        """인용한 근거의 원문을 반환한다."""
        document = by_reference.get(reference.strip())
        if document is None:
            available = ", ".join(sorted(by_reference)) or "(없음)"
            return f"'{reference}' 근거가 없다. 사용 가능한 참조: {available}"
        body = " ".join(document.content.split())[:_SOURCE_MAX_CHARS]
        return f"[{document.reference}] {document.title}\n{body}"

    async def search_pool(query: str) -> str:
        """저장된 자료에서 검색해 빠진 사실이 있는지 확인한다."""
        if not query.strip():
            return "검색어가 비어 있다."
        found = await search_stored_documents(
            connection, user_id=user_id, query=query, topic_intent=topic_intent
        )
        return describe_documents(found)

    return [
        ToolSpec(
            name="get_source",
            description=(
                "인용한 근거의 원문을 읽는다. 초안에는 원문이 없으므로 "
                "인용이 실제로 맞는지 확인하려면 이 도구를 써야 한다."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "reference": {
                        "type": "string",
                        "description": "확인할 참조 ID (예: P1, G2, L3)",
                    }
                },
                "required": ["reference"],
            },
            run=get_source,
        ),
        ToolSpec(
            name="search_pool",
            description=(
                "저장된 자료를 검색한다. 초안이 중요한 사실을 빠뜨렸는지 "
                "확인할 때 사용한다."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "확인할 검색어"}
                },
                "required": ["query"],
            },
            run=search_pool,
        ),
    ]


def parse_verdict(text: str) -> CriticVerdict | None:
    """검토자의 JSON 응답을 판정으로 변환한다. 형식이 어긋나면 None."""
    try:
        payload = json.loads(strip_json_fence(text))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    outcome = str(payload.get("verdict") or "").strip().lower()
    if outcome not in {PASS, REVISE}:
        return None
    problem = str(payload.get("problem") or "").strip()
    correction = str(payload.get("correction") or "").strip()
    if outcome == REVISE and not correction:
        # 무엇을 고치라는지 없으면 재작성해도 같은 글이 나온다.
        correction = problem or "지적된 사실관계 문제를 바로잡아 다시 작성하세요."
    return CriticVerdict(
        outcome=outcome,
        should_regenerate=outcome == REVISE,
        problem=problem,
        correction=correction if outcome == REVISE else "",
    )


async def review_report(
    connection: AsyncConnection[DictRow],
    *,
    content: GeneratedReportContent,
    contexts: Sequence[ReportContextDocument],
    user_id: str,
    topic: str,
    topic_intent: str = "news",
    model: str = "gpt-4o-mini",
    max_iterations: int = CRITIC_MAX_ITERATIONS,
) -> CriticVerdict:
    """검토자가 도구로 근거를 대조해 초안의 사실관계를 판정한다.

    Args:
        connection: 추가 검색에 사용할 DB 연결
        content: 검증할 리포트 초안
        contexts: 생성에 사용한 근거 문서
        user_id: 검색 Scope 사용자 식별자
        topic: 리포트 주제
        topic_intent: 토픽 성격("news"|"evergreen")
        model: 검토에 사용할 모델
        max_iterations: 도구 호출 왕복 상한

    Returns:
        판정 결과. 검토가 불가능하면 outcome="unavailable"로 통과 처리한다.
    """
    if not _reference_index(contexts):
        # 대조할 근거가 없으면(또는 참조 ID가 없는 형태면) 검증할 것이 없다.
        return CriticVerdict(outcome=UNAVAILABLE)

    tools = build_critic_tools(
        connection,
        user_id=user_id,
        contexts=contexts,
        topic_intent=topic_intent,
    )
    try:
        result = await run_tool_loop(
            SYSTEM_PROMPT,
            f"리포트 주제: {topic}\n\n{_draft_prompt(content, contexts)}",
            tools,
            model=model,
            max_iterations=max_iterations,
        )
    except Exception:
        logger.exception("검토자 실행에 실패해 초안을 그대로 통과시킵니다.")
        return CriticVerdict(outcome=UNAVAILABLE)

    verdict = parse_verdict(result.text)
    if verdict is None:
        logger.warning("검토자 응답을 해석하지 못해 통과 처리합니다: %s", result.text[:200])
        return CriticVerdict(
            outcome=UNAVAILABLE,
            calls=result.calls,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )

    logger.info(
        "검토 판정: %s (도구 호출 %d회) — %s",
        verdict.outcome,
        len(result.calls),
        verdict.problem or "문제 없음",
    )
    return CriticVerdict(
        outcome=verdict.outcome,
        should_regenerate=verdict.should_regenerate,
        problem=verdict.problem,
        correction=verdict.correction,
        calls=result.calls,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )
