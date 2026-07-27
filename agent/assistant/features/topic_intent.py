"""토픽의 성격(뉴스형/개념형)을 개인 Wiki 노드 종류로 판정하는 조회 경계.

수집 창과 신선도 감쇠는 토픽 성격에 따라 달라야 한다. '코스피'는 오늘 소식이
중요하지만 'DDD(Domain-Driven Design)'는 몇 달 전 좋은 글이 지금도 유효하다.
같은 기준을 대면 개념형 토픽만 선택적으로 전멸한다(2026-07-27 실측: DDD 리포트
66초 실행에 실시간 자료 0건, 수집된 14건 중 9건이 outside_window로 탈락).

성격 판정에 LLM을 새로 부르지 않고 **개인 Wiki가 이미 내린 판단을 재사용한다.**
Wiki Builder가 문서를 Entity·Concept·Schema로 분류해 `wiki_documents.
document_kind`에 저장해 두었으므로, 같은 질문을 두 번 하지 않는다.

  concept·schema → evergreen (개념·구조 지식, 오래 유효)
  entity·document → news     (실체·사건, 최신성이 중요)

비서는 DB 없이도 동작해야 하므로(content_store.py·storage.py와 같은 원칙)
연결 문자열이 없거나 조회가 실패하거나 Wiki에 없는 토픽이면 기존 동작인
news로 폴백한다 — 판정 실패가 수집을 막지 않는다.
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger("agent.assistant.topic_intent")

# 토픽 성격. selection의 content_type과 같은 어휘를 쓴다(감쇠 상수를 공유한다).
INTENT_NEWS = "news"
INTENT_EVERGREEN = "evergreen"

# Wiki 노드 종류 → 토픽 성격.
_EVERGREEN_KINDS = frozenset({"concept", "schema"})

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


def resolve_topic_intent(topic: str, user_id: str) -> str:
    """토픽이 뉴스형인지 개념형인지 개인 Wiki 노드 종류로 판정한다.

    판정할 수 없으면(DB 없음·Wiki에 없는 토픽·조회 실패) news를 반환해 기존
    동작을 유지한다.

    Args:
        topic: 판정할 토픽
        user_id: 개인 Wiki 조회 Scope에 쓸 사용자 식별자

    Returns:
        INTENT_NEWS 또는 INTENT_EVERGREEN
    """
    key = topic_document_key(topic)
    dsn = os.environ.get("AGENT_DATABASE_URL")
    if not key or not user_id or not dsn:
        return INTENT_NEWS

    try:
        import psycopg

        with psycopg.connect(dsn, connect_timeout=5) as connection, connection.cursor() as cursor:
            # 개인 Wiki는 RLS로 보호되므로 조회 Scope를 먼저 설정한다.
            cursor.execute(
                "SELECT set_config('app.user_id', %s, true), "
                "set_config('app.access_scope', 'user', true)",
                (user_id,),
            )
            # 같은 key가 여러 종류로 있으면(예: '주가'가 concept·entity 양쪽)
            # 개념 쪽을 우선한다 — 넓게 보는 것이 0건보다 낫다.
            cursor.execute(
                """
                SELECT document_kind
                FROM agent.wiki_documents
                WHERE namespace_key = %s
                  AND lower(document_key) = %s
                  AND deleted_at IS NULL
                ORDER BY (document_kind = ANY(%s)) DESC
                LIMIT 1
                """,
                (f"user/{user_id}", key, list(_EVERGREEN_KINDS)),
            )
            row = cursor.fetchone()
    except Exception as error:  # noqa: BLE001 — 판정 실패가 수집을 막으면 안 된다
        logger.info("토픽 성격 판정 실패, news로 폴백한다 (topic=%s): %s", topic, error)
        return INTENT_NEWS

    if not row:
        return INTENT_NEWS
    kind = str(row[0] or "")
    intent = INTENT_EVERGREEN if kind in _EVERGREEN_KINDS else INTENT_NEWS
    logger.info("토픽 성격 판정: %s → %s (Wiki %s)", topic, intent, kind)
    return intent
