"""아침 브리핑 주제 선정 기능.

개인 Wiki에서 뽑은 관심사 후보와 그 **맥락 문장**을 받아, 사용자가 내일 아침에
받아볼 주제를 고른다. 맥락 생성은 Wiki 쪽(이송우) 소유이고 이 모듈은 고르기만
한다 — 함수 호출로 후보를 넘겨받는다(2026-08-10 협의).

**연결 수로 고르던 방식을 대체한다.** 기존 관심사 점수는 구조(연결 수 × 근거
강도 × 최신성)만 보므로, 여러 글에 자주 등장한 것이 곧 관심사가 된다. 실측에서
`DBeaver Community`·`OpenWiki`·`pgAdmin 4`(도구), `기술노트with 알렉`(출처)이
상위를 차지했다. 이름만으로는 이것들을 가릴 수 없어서, 08-08에 넣은 필터는
삼성전자·SK하이닉스까지 함께 지웠고 08-10에 걷어냈다.

맥락 문장이 있으면 갈린다 — "저장된 글 2개 모두 PostgreSQL 튜닝을 다루며
DBeaver는 작업 수단으로만 등장한다"를 읽으면 도구인지 관심사인지 판단된다.

아침 브리핑은 사용자가 결과를 검토하지 않고 그냥 받는 경로다. 잘못 고르면 관심
없는 리포트가 그대로 도착하므로, 이 선정이 아침 품질을 직접 좌우한다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from agent.llm.api import complete, strip_json_fence

logger = logging.getLogger("agent.report_builder.briefing_topics")

_PROMPT_PATH = (
    Path(__file__).parents[2] / "prompts" / "templates" / "briefing_topic_selector.md"
)
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8").strip()

# 아침 브리핑 기본 주제 수. 계약상 topics는 최대 5개까지 보낼 수 있다.
DEFAULT_BRIEFING_TOPIC_COUNT = 3


@dataclass(frozen=True, slots=True)
class InterestCandidate:
    """선정자에게 넘길 관심사 후보 하나.

    Attributes:
        node: Wiki 노드 제목. **이 값이 그대로 검색어가 된다** — 선정 결과도 이
            문자열이어야 창고 검색이 걸린다.
        context: 이 후보가 사용자에게 어떤 의미인지 설명하는 문장. 이름만으로는
            도구·출처를 가릴 수 없어 반드시 필요하다.
    """

    node: str
    context: str = ""


@dataclass(frozen=True, slots=True)
class BriefingTopicSelection:
    """선정 결과.

    Attributes:
        topics: 고른 주제 이름. 후보에 있던 표기를 그대로 쓴다
        reason: 왜 이 조합을 골랐는지. 로그·디버깅용이며 사용자에게 보이지 않는다
    """

    topics: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True, slots=True)
class InterestContext:
    """Wiki 쪽이 넘겨주는 선정 입력 묶음.

    Attributes:
        candidates: 관심사 후보 목록. 구조 점수 상위 15개쯤으로 좁혀 넘긴다 —
            전부 넘기면 노드가 수백 개인 사용자에서 토큰이 커진다
        user_summary: 이 사용자가 전체적으로 무엇에 관심 있는지 요약한 문장.
            개별 후보만 보면 전체 그림을 놓친다
    """

    candidates: Sequence[InterestCandidate] = field(default_factory=tuple)
    user_summary: str = ""


def _build_user_prompt(context: InterestContext, *, limit: int) -> str:
    """후보와 맥락을 선정자에게 넘길 프롬프트로 조립한다."""
    lines = [f"고를 주제 수: {limit}개"]
    if context.user_summary.strip():
        lines.append(f"\n사용자 요약: {context.user_summary.strip()}")
    lines.append("\n후보:")
    for candidate in context.candidates:
        detail = candidate.context.strip()
        lines.append(f"- {candidate.node}" + (f"\n    {detail}" if detail else ""))
    return "\n".join(lines)


def _parse_selection(
    raw_response: str, *, allowed: Sequence[str], limit: int
) -> BriefingTopicSelection:
    """선정자 응답을 검증한다.

    후보에 없는 이름은 버린다. 그 이름이 그대로 검색어가 되므로, 지어낸 주제를
    통과시키면 자료를 한 건도 못 찾고 섹션이 빈다. 리포트 생성이 인용 참조를
    검증하는 것과 같은 이유다.

    대소문자·공백만 다른 표기는 후보 쪽 표기로 되돌린다 — 모델이 띄어쓰기를
    바꿔 쓰는 일이 흔한데, 그것 때문에 멀쩡한 선택을 버릴 이유는 없다.
    """
    payload = json.loads(strip_json_fence(raw_response))
    if not isinstance(payload, dict):
        raise ValueError("아침 주제 선정 응답은 JSON 객체여야 합니다.")
    canonical = {" ".join(name.split()).casefold(): name for name in allowed}
    selected: list[str] = []
    for item in payload.get("topics") or []:
        marker = " ".join(str(item).split()).casefold()
        resolved = canonical.get(marker)
        if resolved is None:
            logger.info("후보에 없는 주제를 버린다: %r", item)
            continue
        if resolved in selected:
            continue
        selected.append(resolved)
        if len(selected) >= limit:
            break
    return BriefingTopicSelection(
        topics=tuple(selected), reason=str(payload.get("reason") or "").strip()
    )


def select_briefing_topics(
    context: InterestContext,
    *,
    limit: int = DEFAULT_BRIEFING_TOPIC_COUNT,
    model: str = "gpt-4.1-mini",
) -> BriefingTopicSelection:
    """맥락을 읽고 아침 브리핑에 쓸 주제를 고른다.

    **실패해도 예외를 올리지 않는다.** 선정이 안 됐다고 아침 브리핑을 통째로
    거르는 것보다, 빈 결과를 돌려주고 호출자가 기존 순서(구조 점수)로 폴백하는
    편이 낫다.

    Args:
        context: Wiki 쪽이 만든 후보와 맥락
        limit: 고를 주제 수
        model: 선정에 쓸 OpenAI 모델

    Returns:
        고른 주제와 사유. 후보가 없거나 호출·파싱이 실패하면 빈 결과
    """
    candidates = [
        candidate for candidate in context.candidates if candidate.node.strip()
    ]
    if not candidates or limit <= 0:
        return BriefingTopicSelection()
    # 후보가 고를 개수 이하면 물어볼 것이 없다. 호출을 아낀다.
    if len(candidates) <= limit:
        return BriefingTopicSelection(
            topics=tuple(candidate.node for candidate in candidates),
            reason="후보가 고를 개수 이하라 그대로 사용했다.",
        )

    prompt = _build_user_prompt(
        InterestContext(candidates=candidates, user_summary=context.user_summary),
        limit=limit,
    )
    try:
        raw = complete(_SYSTEM_PROMPT, prompt, model=model)
        selection = _parse_selection(
            raw, allowed=[candidate.node for candidate in candidates], limit=limit
        )
    except Exception as error:  # noqa: BLE001 — 선정 실패가 브리핑을 막으면 안 된다
        logger.warning("아침 주제 선정 실패, 빈 결과를 돌려준다: %s", error)
        return BriefingTopicSelection()

    logger.info(
        "아침 주제 선정: %s (후보 %d개 중, 사유=%s)",
        ", ".join(selection.topics),
        len(candidates),
        selection.reason,
    )
    return selection
