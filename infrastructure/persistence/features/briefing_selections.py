"""아침 브리핑 주제 선정 결과를 읽고 저장한다.

Service가 03:00에 미리 물어본 주제를 07:00 호출에서 그대로 돌려주기 위한
저장소다. 유효성은 시간이 아니라 후보 목록의 지문(`candidate_digest`)으로
판단한다 — 주제는 뉴스가 아니라 개인 Wiki 후보에서 나오므로, 후보가 그대로면
몇 시간이 지나도 같은 답이 맞다.
"""

from __future__ import annotations

from dataclasses import dataclass

from psycopg import AsyncConnection
from psycopg.rows import DictRow


@dataclass(frozen=True)
class StoredBriefingTopicSelection:
    """저장해 둔 아침 주제 선정 결과.

    Attributes:
        topics: 고른 주제. 순서가 의미를 가진다
        reason: 선정 사유
        candidate_count: 선정에 검토한 후보 수
    """

    topics: tuple[str, ...]
    reason: str
    candidate_count: int


async def load_briefing_topic_selection(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    candidate_digest: str,
    topic_limit: int,
) -> StoredBriefingTopicSelection | None:
    """후보 지문과 주제 수가 모두 일치하는 저장 결과를 읽는다.

    지문이 다르면 밤사이 Wiki가 바뀐 것이므로 재사용하지 않는다. 주제 수까지
    대조하는 이유는, 3개를 요청했는데 2개로 저장된 결과를 그대로 돌려주면
    호출자와의 계약이 깨지기 때문이다.

    Args:
        connection: 이미 열린 agent-db 연결
        user_id: 조회 대상 사용자 ID
        candidate_digest: 이번 요청의 후보 목록 지문
        topic_limit: 이번 요청이 고르려는 주제 수

    Returns:
        재사용할 수 있는 선정 결과. 없거나 조건이 다르면 None
    """
    cursor = await connection.execute(
        """
        SELECT topics, reason, candidate_count
        FROM agent.briefing_topic_selections
        WHERE user_id = %s
          AND candidate_digest = %s
          AND topic_limit = %s
        """,
        (user_id, candidate_digest, topic_limit),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return StoredBriefingTopicSelection(
        topics=tuple(str(topic) for topic in (row["topics"] or [])),
        reason=str(row["reason"] or ""),
        candidate_count=int(row["candidate_count"] or 0),
    )


async def save_briefing_topic_selection(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    candidate_digest: str,
    topics: list[str],
    reason: str,
    candidate_count: int,
    topic_limit: int,
) -> None:
    """이번에 고른 주제를 사용자당 한 행으로 덮어쓴다.

    이력을 쌓지 않는다. 필요한 것은 "가장 최근에 무엇으로 골랐나" 하나뿐이고,
    쌓아 두면 어느 행을 재사용할지 다시 판단해야 한다.

    Args:
        connection: 이미 열린 agent-db 연결
        user_id: 대상 사용자 ID
        candidate_digest: 선정 입력이 된 후보 목록 지문
        topics: 고른 주제 목록
        reason: 선정 사유
        candidate_count: 검토한 후보 수
        topic_limit: 이번 요청이 고르려던 주제 수
    """
    await connection.execute(
        """
        INSERT INTO agent.briefing_topic_selections (
            user_id, candidate_digest, topics, reason, candidate_count, topic_limit
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            candidate_digest = EXCLUDED.candidate_digest,
            topics = EXCLUDED.topics,
            reason = EXCLUDED.reason,
            candidate_count = EXCLUDED.candidate_count,
            topic_limit = EXCLUDED.topic_limit,
            selected_at = clock_timestamp(),
            updated_at = clock_timestamp()
        """,
        (user_id, candidate_digest, list(topics), reason, candidate_count, topic_limit),
    )
