"""주제별 보조 검색어 생성 기능.

주제어 하나로만 수집하면 그 단어가 제목에 든 자료만 걸린다(2026-08-11 실측:
`다낭 여행` 섹션이 여행사 보도자료로 채워져 "아름다운 해변과 풍부한 문화유산"
같은 홍보 문구만 남았다). 사용자가 알고 싶은 추천 장소·날씨·랜드마크는 다른
말로 쓰여 있어서 애초에 검색에 안 걸린다.

**기존 확장은 Wiki 이웃에만 의존한다.** `코스피`처럼 오래된 관심사는 위키에
`코스닥`·`한국거래소`가 이어져 있어 확장이 되는데, 방금 생긴 관심사는 이웃이
없어 검색어가 하나뿐이다. 새 관심사일수록 창고가 얕은데 검색은 더 좁아지는
셈이라, 품질이 가장 나쁜 쪽이 가장 적게 찾는다.

**주제 성격에 따라 묻는 것이 다르다.** 뉴스형은 "무엇이 달라졌나", 개념형은
"무엇을 알아야 하나"를 물어야 한다. 그 판정(`resolve_topic_intent`)은 이미
리포트 생성에서 쓰고 있으므로 그대로 받아 쓴다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from agent.llm.api import complete, strip_json_fence

logger = logging.getLogger("agent.report_builder.topic_facets")

_PROMPT_PATH = (
    Path(__file__).parents[2] / "prompts" / "templates" / "topic_facet_queries.md"
)
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8").strip()

# 주제당 만들 보조 검색어 수. 수집은 검색어마다 소스를 돌므로 늘리면 그만큼
# 외부 호출과 시간이 는다.
DEFAULT_FACET_LIMIT = 3


def _marker(text: str) -> str:
    """같은 검색어인지 비교할 표기를 만든다."""
    return "".join(text.split()).casefold()


def generate_topic_facets(
    topic: str,
    *,
    intent: str = "news",
    context: str = "",
    limit: int = DEFAULT_FACET_LIMIT,
    model: str = "gpt-4o-mini",
) -> tuple[str, ...]:
    """주제와 함께 찾아볼 보조 검색어를 만든다.

    **실패해도 예외를 올리지 않는다.** 검색어를 못 만들었다고 수집을 막을 이유는
    없다 — 빈 목록을 돌려주면 호출자가 기존처럼 주제어 하나로 수집한다.

    원 주제와 같은 뜻인 검색어는 버린다. 같은 검색을 두 번 하면 외부 호출만 늘고
    결과는 그대로다.

    Args:
        topic: 관심 주제
        intent: 주제 성격("news"|"evergreen"). 무엇을 물을지가 갈린다
        context: 이 주제가 무엇인지 알려주는 한 줄. 없으면 이름만 보고 만든다
        limit: 만들 보조 검색어 수
        model: 사용할 OpenAI 모델

    Returns:
        보조 검색어. 원 주제는 포함하지 않는다. 실패하면 빈 Tuple
    """
    normalized = topic.strip()
    if not normalized or limit <= 0:
        return ()

    hint = " ".join(context.split())
    prompt = (
        f"주제: {normalized}\n"
        + (f"주제 설명: {hint}\n" if hint else "")
        + f"intent: {intent}\n만들 검색어 수: {limit}개"
    )
    try:
        raw = complete(_SYSTEM_PROMPT, prompt, model=model)
        payload = json.loads(strip_json_fence(raw))
        if not isinstance(payload, dict):
            raise ValueError("보조 검색어 응답은 JSON 객체여야 합니다.")
        candidates = payload.get("queries") or []
    except Exception as error:  # noqa: BLE001 — 확장 실패가 수집을 막으면 안 된다
        logger.warning("보조 검색어 생성 실패, 주제어로만 수집한다 (%s): %s", topic, error)
        return ()

    seen = {_marker(normalized)}
    queries: list[str] = []
    for candidate in candidates:
        query = " ".join(str(candidate).split())
        marker = _marker(query)
        if not query or marker in seen:
            continue
        seen.add(marker)
        queries.append(query)
        if len(queries) >= limit:
            break
    logger.info("보조 검색어 %s (intent=%s) → %s", topic, intent, queries)
    return tuple(queries)
