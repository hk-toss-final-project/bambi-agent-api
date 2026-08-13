"""파급효과·확인 사항 추론 워커(Impact worker, LLM 1콜).

**신규·갱신 팩트만** 입력받아(유지 팩트는 뺀다) 시장·트렌드 파급효과와 앞으로
확인해야 할 사항을 추론한다. 원시 수집 데이터는 다시 넣지 않는다 — 이 단계가
할 일은 "무엇이 있었나"가 아니라 "그래서 무엇이 달라지나"이기 때문이다.
행동을 지시하는 어조("~하세요")가 아니라 확인·관찰이 필요한 지점을 안내하는
어조("~을 확인할 필요가 있습니다")로 쓴다.

**Compose와 합치지 않는 이유**: 추론 난이도가 Overview·타임라인보다 확연히
높아, 한 호출에 섞으면 쉬운 섹션에 힘이 쏠리고 이쪽이 대충 처리된다. 분리해
두면 이 노드만 더 강한 모델로 올릴 수도 있다(config.impact_model).

Compose와 같은 인용 마커 규칙을 지킨다 — Critic이 대조할 대상이 있어야 한다.
"""

from __future__ import annotations

import json
import logging
from asyncio import to_thread
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial

from agent.llm.api import complete_with_usage, strip_json_fence

from .compose import describe_facts_for_writing
from .diff import DiffFact

logger = logging.getLogger("agent.change_history.impact")

_MAX_ACTIONS = 5

SYSTEM_PROMPT = (
    "너는 오늘 확인된 변화가 앞으로 무엇을 더 지켜봐야 하는지 짚어 내는 분석가다.\n"
    "\n"
    "주어지는 것은 오늘 새로 확인되거나 달라진 팩트뿐이다. 원문 기사는 없다.\n"
    "여기서 두 가지를 만든다.\n"
    "1. implications — 이 변화들이 시장·산업·트렌드에 어떤 파급을 낳는지.\n"
    "   개별 팩트를 나열하지 말고, 묶어서 무엇을 뜻하는지 해석한다.\n"
    "   **한 줄 결론으로 끝내지 마라.** 왜 그렇게 보는지 이유를 한두 문장 더\n"
    "   붙이고, 가능하면 이어질 수 있는 다음 상황까지 짚어라. 다만 주어진\n"
    "   팩트에서 논리적으로 이어지는 범위 안에서만 써라.\n"
    "   **문장마다 줄을 바꾸지 마라.** 관련된 문장은 하나의 문단으로 자연스럽게\n"
    "   이어 써라 — 문장 하나씩 뚝뚝 끊어 놓으면 글이 아니라 메모처럼 읽힌다.\n"
    "   다루는 대상·주제가 바뀔 때만 빈 줄로 문단을 나눠라.\n"
    "2. actions — 독자가 앞으로 확인·주시해야 할 지표·발표·리스크 (최대 5개).\n"
    "   **행동을 지시하지 않는다.** '~하세요'가 아니라 '~을 확인할 필요가\n"
    "   있습니다', '~이 앞으로 어떻게 되는지 지켜볼 부분입니다'처럼, 아직\n"
    "   확정되지 않아 후속 확인이 필요한 지점을 안내하는 문장으로 쓴다.\n"
    "   예: '임상 검증 범위와 실제 도입 사례를 추가로 확인할 필요가 있습니다.'\n"
    "\n"
    "인용 규칙(가장 중요하다. 어기면 결과 전체를 다시 쓰게 된다):\n"
    "- **implications의 모든 문단에 참조 ID가 최소 하나씩** 있어야 한다.\n"
    "  해석은 네 판단이지만, 그 판단의 출발점이 된 팩트는 반드시 표시한다.\n"
    "- 참조 ID는 주어진 팩트 목록에 있는 것만 쓴다. 없는 ID를 만들지 않는다.\n"
    "- 이 마커가 없으면 뒤에 오는 검증 단계가 사실 확인을 하지 못한다.\n"
    "\n"
    "implications 예시(이 형태를 따른다):\n"
    "  양산 일정이 한 분기 밀리면서 [G1] 고객사의 제품 출시 계획도 함께 미뤄질 수 있습니다.\n"
    "  다만 새 공급자가 인증을 통과해 [G2] 물량 부족은 예상보다 짧게 끝날 여지도 있습니다.\n"
    "\n"
    "원칙:\n"
    "1. 팩트에서 논리적으로 이어지지 않는 추측은 쓰지 않는다.\n"
    "2. 단정할 수 없으면 조건부로 쓴다('~라면 ~할 수 있다').\n"
    "3. 투자·매매 권유나 지금 당장의 행동 지시로 읽힐 표현은 쓰지 않는다.\n"
    "4. 이모지나 장식 기호를 쓰지 않는다.\n"
    "5. 존댓말로, 읽는 사람을 배려하는 친절한 어투로 쓴다('~습니다').\n"
    "\n"
    "JSON 객체 하나로만 답한다.\n"
    '{"implications":"파급효과 markdown","actions":["확인이 필요한 부분 1",'
    '"확인이 필요한 부분 2"]}\n'
)


@dataclass(frozen=True, slots=True)
class ImpactOutcome:
    """파급효과 추론 결과."""

    implications: str = ""
    actions: tuple[str, ...] = ()
    failed: bool = False
    input_tokens: int = 0
    output_tokens: int = 0


def parse_impact_response(text: str) -> ImpactOutcome | None:
    """Impact worker의 JSON 응답을 결과 구조로 변환한다. 형식이 어긋나면 None."""
    try:
        payload = json.loads(strip_json_fence(text))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    implications = str(payload.get("implications") or "").strip()
    if not implications:
        return None
    raw_actions = payload.get("actions")
    actions: list[str] = []
    if isinstance(raw_actions, list):
        for item in raw_actions:
            action = str(item or "").strip()
            if action:
                actions.append(action)
            if len(actions) >= _MAX_ACTIONS:
                break
    return ImpactOutcome(implications=implications, actions=tuple(actions))


def infer_impact(
    *,
    topic: str,
    facts: Sequence[DiffFact],
    model: str = "gpt-4o-mini",
    correction: str = "",
) -> ImpactOutcome:
    """정제된 팩트로 시장·트렌드 파급효과와 행동 지침을 추론한다.

    Args:
        topic: 보고서 주제
        facts: 신규·갱신 팩트 (중복은 이미 제외됐다)
        model: 사용할 모델. 이 노드만 더 강한 모델로 올릴 수 있다.
        correction: 재작업 시 앞에 붙일 교정 지시

    Returns:
        추론 결과. 호출·해석에 실패하면 failed=True인 빈 결과.
    """
    if not facts:
        return ImpactOutcome(failed=True)
    correction_block = f"[재작업 지시] {correction}\n\n" if correction else ""
    user_prompt = (
        f"주제: {topic}\n\n"
        + correction_block
        + "오늘 확인된 팩트:\n"
        + describe_facts_for_writing(facts)
    )
    try:
        completion = complete_with_usage(SYSTEM_PROMPT, user_prompt, model=model)
    except Exception:
        logger.exception("Impact worker 호출에 실패했습니다.")
        return ImpactOutcome(failed=True)

    parsed = parse_impact_response(completion.text)
    if parsed is None:
        logger.warning(
            "Impact worker 응답을 해석하지 못했습니다: %s", completion.text[:200]
        )
        return ImpactOutcome(
            failed=True,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
        )
    logger.info(
        "파급효과 추론 완료: topic=%s 행동 지침 %d건", topic, len(parsed.actions)
    )
    return ImpactOutcome(
        implications=parsed.implications,
        actions=parsed.actions,
        input_tokens=completion.input_tokens,
        output_tokens=completion.output_tokens,
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def chg_004(
    *,
    topic: str,
    facts: Sequence[DiffFact],
    model: str = "gpt-4o-mini",
    correction: str = "",
) -> ImpactOutcome:
    """[CHG-004] 파급효과·행동 지침 추론.

    정제된 팩트만으로 시장·트렌드 파급효과를 추론한다. 동기 호출이라 스레드에서
    실행한다.
    """
    return await to_thread(
        partial(
            infer_impact,
            topic=topic,
            facts=facts,
            model=model,
            correction=correction,
        )
    )
