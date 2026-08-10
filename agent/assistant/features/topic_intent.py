"""토픽에 최신 자료가 얼마나 필요한지 판정하는 경계.

수집 창과 신선도 하한은 토픽 성격에 따라 달라야 한다. '코스피'는 오늘 소식이
중요하지만 'DDD(Domain-Driven Design)'는 몇 달 전 좋은 글이 지금도 유효하다.
같은 기준을 대면 개념형 토픽만 선택적으로 전멸한다(2026-07-27 실측: DDD 리포트
66초 실행에 실시간 자료 0건, 수집된 14건 중 9건이 outside_window로 탈락).

**개인 Wiki 노드 종류(entity/concept)로 대신 판정하던 것을 2026-08-10에 걷어냈다.**
"개념이냐"와 "최신 소식이 필요하냐"는 다른 질문인데 하나로 묶여 있었다. 실측:
user 57의 아침 브리핑이 일주일 전 로또 1235회 기사를 근거로 삼아 "다음 추첨은
8월 8일 예정"이라고 썼다(그날은 8월 10일이었다). '로또'가 Wiki에 concept으로
저장돼 evergreen(90일)으로 판정된 탓이다. 같은 계정의 '수면'·'멘탈'도 같은
상태였고, 회차 번호가 없어 눈에 띄지 않았을 뿐이다.

지금은 주제 문자열 자체를 LLM에 물어 판정한다. 로또·환율·반도체처럼 개념이면서
시의성이 중요한 주제를 가려내려면 형태가 아니라 의미를 봐야 한다.

판정 실패(키 없음·호출 실패·모르는 응답)는 news로 폴백한다 — 오래된 자료를 쓰는
실수가 최신 자료만 쓰는 실수보다 나쁘기 때문이다. 판정 실패가 수집을 막지 않는다.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from threading import Lock

from agent.llm.api import complete

logger = logging.getLogger("agent.assistant.topic_intent")

# 토픽 성격. selection의 content_type과 같은 어휘를 쓴다(감쇠 상수를 공유한다).
INTENT_NEWS = "news"
INTENT_EVERGREEN = "evergreen"

_PROMPT_PATH = (
    Path(__file__).parents[2] / "prompts" / "templates" / "topic_freshness_classifier.md"
)
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8").strip()
_MODEL = os.environ.get("TOPIC_INTENT_MODEL", "gpt-4.1-mini")

# 같은 주제를 반복해 묻지 않는다. 아침 브리핑은 매일 같은 주제로 돌고, 여러 주제를
# 묶는 리포트는 한 번에 최대 5회를 부른다. 프로세스 수명 동안만 유지하는 캐시라
# 판정 기준을 바꾸면 재시작으로 비워진다.
_CACHE: dict[str, str] = {}
_CACHE_LOCK = Lock()

# document_key는 소문자·하이픈 형식이다. 공백뿐 아니라 괄호·따옴표 같은 기호도
# 하이픈으로 접히므로(실측: "DDD(Domain-Driven Design)" → "ddd-domain-driven-design")
# 한글·영숫자가 아닌 문자를 모두 구분자로 본다.
_KEY_SEPARATOR_PATTERN = re.compile(r"[^0-9a-z가-힣]+")


def topic_document_key(topic: str) -> str:
    """토픽 문자열을 Wiki document_key 형식으로 정규화한다.

    Args:
        topic: 사용자 관심 토픽 (예: "ADR 상장")

    Returns:
        조회에 쓸 key (예: "adr-상장"). 빈 토픽이면 빈 문자열.
    """
    normalized = _KEY_SEPARATOR_PATTERN.sub("-", topic.strip().lower())
    return normalized.strip("-")


def resolve_topic_intent(topic: str, user_id: str = "") -> str:
    """토픽에 최신 자료가 필요한지(news) 오래된 자료도 유효한지(evergreen) 판정한다.

    주제 문자열만 보고 LLM에게 묻는다. 형태(인물·개념)가 아니라 시의성으로
    갈라야 하기 때문이다 — '로또'와 '반도체'는 개념처럼 생겼지만 사용자가 원하는
    건 이번 주 소식이고, '인덱스 튜닝'은 몇 달 전 글도 그대로 쓸모 있다.

    같은 주제는 프로세스 안에서 한 번만 묻는다. 아침 브리핑은 매일 같은 주제로
    돌고, 여러 주제를 묶는 리포트는 한 번에 여러 번 부른다.

    판정할 수 없으면 news를 반환한다. 오래된 자료를 최신 소식처럼 쓰는 실수가
    최신 자료만 쓰는 실수보다 나쁘다.

    Args:
        topic: 판정할 토픽
        user_id: 쓰지 않는다. 기존 호출부 서명을 유지하려고 남겨 둔 인자다
            (판정이 더 이상 개인 Wiki를 보지 않는다).

    Returns:
        INTENT_NEWS 또는 INTENT_EVERGREEN
    """
    normalized = " ".join(topic.split()).lower()
    if not normalized:
        return INTENT_NEWS
    with _CACHE_LOCK:
        cached = _CACHE.get(normalized)
    if cached is not None:
        return cached

    try:
        raw = complete(_SYSTEM_PROMPT, f"주제: {topic}", model=_MODEL)
    except Exception as error:  # noqa: BLE001 — 판정 실패가 생성을 막으면 안 된다
        logger.info("토픽 성격 판정 실패, news로 폴백한다 (topic=%s): %s", topic, error)
        return INTENT_NEWS

    answer = str(raw or "").strip().strip("`\"' .").lower()
    intent = INTENT_EVERGREEN if answer == INTENT_EVERGREEN else INTENT_NEWS
    if answer not in (INTENT_NEWS, INTENT_EVERGREEN):
        logger.info("토픽 성격 판정 응답을 알 수 없어 news로 둔다 (topic=%s): %r", topic, raw)
    else:
        logger.info("토픽 성격 판정: %s → %s", topic, intent)
    with _CACHE_LOCK:
        _CACHE[normalized] = intent
    return intent


def clear_topic_intent_cache() -> None:
    """판정 캐시를 비운다(테스트·운영 점검용)."""
    with _CACHE_LOCK:
        _CACHE.clear()
