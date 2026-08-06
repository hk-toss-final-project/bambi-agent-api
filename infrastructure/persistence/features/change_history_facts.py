"""변경점(Delta) 추적 팩트와 실행 메타의 영속화.

`agent.change_history_facts`·`agent.change_history_runs`(0012 Migration)에
raw SQL로 접근한다. 이 저장소는 **다음 실행의 Base 재료**이므로, 조회는 항상
(user_id, topic) 두 조건으로 격리하고 저장은 첫 실행에서도 빠짐없이 수행한다.

기존 generation_runs·generated_content_candidates·publish_snapshots 저장
흐름은 건드리지 않는다 — 이 모듈은 그 옆에 추가되는 별도 경계다.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from shared.change_history_models import (
    ChangeHistoryFact,
    ChangeHistoryRunRecord,
    LatestReportSnapshot,
    NewChangeHistoryFact,
    PersistedChangeHistoryRun,
    UPDATED,
)

type DictRow = dict[str, Any]

# 도구 한 번 호출로 돌려줄 과거 팩트 상한. 하루 처리량이 (user, topic)당 수십
# 건 수준이라 이 정도면 대조에 충분하고, 관찰 문자열도 대화를 넘치지 않는다.
BASE_FACT_SEARCH_LIMIT = 12
# Base 맥락·전체 조회 상한.
BASE_FACT_LIST_LIMIT = 60


def _uuid_or_none(value: str | None) -> str | None:
    """UUID 형식이 아닌 값은 None으로 바꿔 잘못된 FK 저장을 막는다."""
    if not value:
        return None
    try:
        UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None
    return str(value)


def _fact_from_row(row: DictRow) -> ChangeHistoryFact:
    """조회 Row를 공유 팩트 구조로 변환한다."""
    return ChangeHistoryFact(
        fact_id=str(row["id"]),
        subject=str(row["subject"]),
        attribute=str(row["attribute"]),
        fact_value=str(row["fact_value"] or ""),
        statement=str(row["statement"]),
        verdict=str(row["verdict"]),
        occurred_on=row.get("occurred_on"),
        date_precision=str(row.get("date_precision") or "unknown"),
        source_reference=row.get("source_reference"),
        source_url=row.get("source_url"),
    )


async def load_latest_report_snapshot(
    connection: AsyncConnection[DictRow], *, user_id: str, topic: str
) -> LatestReportSnapshot | None:
    """(user_id, topic)의 가장 최근 발행 Snapshot 본문을 조회한다.

    Overview가 과거 맥락으로 삼는 (a)맥락 요약이다. topic은 Snapshot Payload가
    아니라 generation_requests에서 확인한다 — 요청 시 확정된 값이라 더 정확하다.

    Args:
        connection: 이미 열린 agent-db 커넥션
        user_id: 조회 대상 사용자 식별자
        topic: 보고서 주제

    Returns:
        최신 Snapshot 본문. 이 주제로 발행한 적이 없으면 None.
    """
    cursor = await connection.execute(
        """
        SELECT snapshot.payload, snapshot.created_at
        FROM agent.publish_snapshots AS snapshot
        JOIN agent.generated_content_candidates AS candidate
            ON candidate.id = snapshot.candidate_id
        JOIN agent.generation_requests AS request
            ON request.id = candidate.generation_request_id
        WHERE snapshot.user_id = %s AND request.topic = %s
        ORDER BY snapshot.created_at DESC
        LIMIT 1
        """,
        (user_id, topic),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    payload = row.get("payload") or {}
    if not isinstance(payload, dict):
        return None
    return LatestReportSnapshot(
        title=str(payload.get("title") or ""),
        summary=str(payload.get("summary") or ""),
        body=str(payload.get("body") or ""),
        created_at=str(row.get("created_at") or ""),
    )


async def load_latest_change_history_run(
    connection: AsyncConnection[DictRow], *, user_id: str, topic: str
) -> ChangeHistoryRunRecord | None:
    """(user_id, topic)의 직전 변경점 추적 실행을 조회한다.

    "어제 날짜"가 아니라 이 실행 기록이 델타의 기준점이다. 매일 실행되지
    않아도 마지막 실행 이후의 변화를 그대로 이어서 볼 수 있다.

    Returns:
        직전 실행 기록. 첫 실행이면 None.
    """
    cursor = await connection.execute(
        """
        SELECT
            id,
            user_id,
            topic,
            reference_date,
            is_first_run,
            outcome,
            new_fact_count,
            updated_fact_count,
            duplicate_fact_count
        FROM agent.change_history_runs
        WHERE user_id = %s AND topic = %s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id, topic),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return ChangeHistoryRunRecord(
        run_id=str(row["id"]),
        user_id=str(row["user_id"]),
        topic=str(row["topic"]),
        reference_date=row["reference_date"],
        is_first_run=bool(row["is_first_run"]),
        outcome=str(row["outcome"]),
        new_fact_count=int(row["new_fact_count"]),
        updated_fact_count=int(row["updated_fact_count"]),
        duplicate_fact_count=int(row["duplicate_fact_count"]),
    )


async def search_change_history_facts(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    topic: str,
    query: str,
    limit: int = BASE_FACT_SEARCH_LIMIT,
) -> list[ChangeHistoryFact]:
    """이 (user_id, topic)의 누적 과거 팩트 중 검색어와 관련된 것만 조회한다.

    Diff worker의 유일한 도구(search_base_facts)가 쓰는 조회 경계다. 임베딩·
    벡터스토어는 이 규모((user, topic)당 하루 수십 건)에 과설계라, subject·
    attribute·statement를 이어 붙인 문자열에 trigram 유사도를 적용한다.

    **임계값으로 거르지 않고 관련도 순으로 정렬해 상위 N건을 돌려준다.**
    trigram 임계값 방식은 두 번 연속 조용히 실패했다(2026-08-06 실측).

      1. `%`(similarity)는 문자열 **전체**끼리 비교해서, 짧은 검색어를 긴 팩트
         문장과 견주면 점수가 바닥이었다 — '코스피' vs 코스피 팩트가 0.093으로
         기본 임계값 0.3에 미달해 **모든 검색이 0건**을 돌려줬다.
      2. `<%`(word_similarity)로 바꿔도, LLM이 실제로 쓰는 서술형 검색어는
         여전히 걸러졌다 — '코스닥 상승폭 28%'가 0.36으로 기본 임계값 0.6에
         미달했다(단어 하나짜리 '코스닥'은 1.00).

    두 경우 모두 Diff worker가 도구를 불러도 "과거 기록 없음"을 받아, 중복·갱신
    판정이 통째로 죽고 같은 팩트가 매번 신규로 저장됐다. **팩트가 있는데 빈
    결과를 주는 것이 이 기능에서 가장 해로운 실패**라서, 임계값을 다시 튜닝하는
    대신 필터를 없앴다. (user, topic)당 팩트가 수십 건 규모라 상위 N건만 보여도
    후보를 놓치지 않고, 최종 매칭 판단은 어차피 LLM이 한다.

    Args:
        connection: 이미 열린 agent-db 커넥션
        user_id: 조회 Scope 사용자 식별자
        topic: 보고서 주제
        query: 검색어
        limit: 반환할 최대 팩트 수

    Returns:
        유사도 순으로 정렬된 활성 과거 팩트 목록. 검색어가 비면 빈 목록.
    """
    if not query.strip():
        return []
    cursor = await connection.execute(
        """
        SELECT
            id,
            subject,
            attribute,
            fact_value,
            statement,
            verdict,
            occurred_on,
            date_precision,
            source_reference,
            source_url
        FROM agent.change_history_facts
        WHERE user_id = %s
          AND topic = %s
          AND status = 'active'
        ORDER BY
            word_similarity(%s, subject || ' ' || attribute || ' ' || statement) DESC,
            created_at DESC
        LIMIT %s
        """,
        (user_id, topic, query, limit),
    )
    rows = await cursor.fetchall()
    return [_fact_from_row(row) for row in rows]


async def list_change_history_facts(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    topic: str,
    limit: int = BASE_FACT_LIST_LIMIT,
) -> list[ChangeHistoryFact]:
    """이 (user_id, topic)의 활성 과거 팩트를 최신순으로 조회한다.

    검색어 없이 Base가 있는지 확인하거나(Supervisor의 첫 실행 판정), 웹 테스트
    페이지가 누적 팩트를 보여줄 때 쓴다.
    """
    cursor = await connection.execute(
        """
        SELECT
            id,
            subject,
            attribute,
            fact_value,
            statement,
            verdict,
            occurred_on,
            date_precision,
            source_reference,
            source_url
        FROM agent.change_history_facts
        WHERE user_id = %s AND topic = %s AND status = 'active'
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (user_id, topic, limit),
    )
    rows = await cursor.fetchall()
    return [_fact_from_row(row) for row in rows]


async def load_change_history_facts_by_ids(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    topic: str,
    fact_ids: Sequence[str],
) -> dict[str, ChangeHistoryFact]:
    """지정한 팩트 ID 중 이 (user_id, topic) 소속인 것만 조회한다.

    검증(팩트 정합성)이 쓰는 조회다. Diff worker가 찍은 updates_fact_id가
    (1) 실제로 존재하는지 (2) 이 사용자·주제 소속인지를 한 번에 확인하며,
    before 문구도 여기서 읽은 값을 그대로 쓴다.

    UUID 형식이 아닌 값은 조회 전에 걸러낸다 — LLM이 "P1" 같은 참조나 문장을
    ID 자리에 넣으면 psycopg가 타입 오류로 실패해 실행 전체가 죽기 때문이다.

    Returns:
        fact_id를 키로 하는 팩트 사전. 없는 ID는 키가 생기지 않는다.
    """
    candidates = [
        value for value in (_uuid_or_none(fact_id) for fact_id in fact_ids) if value
    ]
    if not candidates:
        return {}
    cursor = await connection.execute(
        """
        SELECT
            id,
            subject,
            attribute,
            fact_value,
            statement,
            verdict,
            occurred_on,
            date_precision,
            source_reference,
            source_url
        FROM agent.change_history_facts
        WHERE user_id = %s AND topic = %s AND id = ANY(%s::uuid[])
        """,
        (user_id, topic, candidates),
    )
    rows = await cursor.fetchall()
    return {str(row["id"]): _fact_from_row(row) for row in rows}


async def persist_change_history_run(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    topic: str,
    reference_date: date,
    facts: Sequence[NewChangeHistoryFact],
    job_id: str | None = None,
    generation_run_id: str | None = None,
    base_run_id: str | None = None,
    is_first_run: bool = False,
    outcome: str = "delta",
    duplicate_fact_count: int = 0,
    dropped_flags: Sequence[dict[str, object]] = (),
) -> PersistedChangeHistoryRun:
    """델타 실행과 이번에 추출한 팩트를 저장한다.

    **첫 실행도 예외 없이 저장한다.** 이 저장은 출력이 아니라 다음 실행의
    Base 재료이며, 여기서 빠지면 내일 대조할 대상이 사라진다.

    갱신 팩트는 새 Row를 넣고 과거 팩트를 superseded로 내린다 — 과거값을
    덮어쓰지 않고 남겨야 before/after 대비와 이력 추적이 가능하다.

    Args:
        connection: 이미 열린 agent-db 커넥션 (Transaction은 호출자가 연다)
        user_id: 대상 사용자 식별자
        topic: 보고서 주제
        reference_date: 절대 날짜 정형화에 사용한 기준일
        facts: 저장할 신규·갱신 팩트 (중복은 호출자가 이미 제외했다)
        job_id·generation_run_id·base_run_id: 추적용 연결 식별자
        is_first_run: 비교 대상이 없던 최초 실행인지
        outcome: delta·no_change·failed
        duplicate_fact_count: 중복으로 판정해 저장하지 않은 팩트 수
        dropped_flags: 검증 재작업 후에도 실패해 드롭한 항목과 사유

    Returns:
        저장된 실행 ID와 팩트 ID 목록
    """
    new_count = sum(1 for fact in facts if fact.verdict != UPDATED)
    updated_count = sum(1 for fact in facts if fact.verdict == UPDATED)
    run_cursor = await connection.execute(
        """
        INSERT INTO agent.change_history_runs (
            user_id,
            topic,
            job_id,
            generation_run_id,
            base_run_id,
            reference_date,
            is_first_run,
            outcome,
            new_fact_count,
            updated_fact_count,
            duplicate_fact_count,
            dropped_flags
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            user_id,
            topic,
            _uuid_or_none(job_id),
            _uuid_or_none(generation_run_id),
            _uuid_or_none(base_run_id),
            reference_date,
            is_first_run,
            outcome,
            new_count,
            updated_count,
            duplicate_fact_count,
            Jsonb(list(dropped_flags)),
        ),
    )
    run_row = await run_cursor.fetchone()
    if run_row is None:
        raise RuntimeError("변경점 추적 실행 기록을 저장하지 못했습니다.")
    run_id = str(run_row["id"])

    fact_ids: list[str] = []
    superseded: list[str] = []
    for fact in facts:
        supersedes = _uuid_or_none(fact.supersedes_fact_id)
        fact_cursor = await connection.execute(
            """
            INSERT INTO agent.change_history_facts (
                run_id,
                user_id,
                topic,
                subject,
                attribute,
                fact_value,
                statement,
                verdict,
                supersedes_fact_id,
                occurred_on,
                date_precision,
                source_reference,
                source_url
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                run_id,
                user_id,
                topic,
                fact.subject,
                fact.attribute,
                fact.fact_value,
                fact.statement,
                fact.verdict,
                supersedes,
                fact.occurred_on,
                fact.date_precision,
                fact.source_reference,
                fact.source_url,
            ),
        )
        fact_row = await fact_cursor.fetchone()
        if fact_row is not None:
            fact_ids.append(str(fact_row["id"]))
        if supersedes:
            # 갱신된 과거 팩트는 지우지 않고 내려 둔다. 다음 실행의 검색 대상에서만
            # 빠지고, before 값을 읽는 ID 조회로는 계속 접근할 수 있다.
            await connection.execute(
                """
                UPDATE agent.change_history_facts
                SET status = 'superseded'
                WHERE id = %s AND user_id = %s AND topic = %s
                """,
                (supersedes, user_id, topic),
            )
            superseded.append(supersedes)
    return PersistedChangeHistoryRun(
        run_id=run_id,
        fact_ids=tuple(fact_ids),
        superseded_fact_ids=tuple(superseded),
    )
