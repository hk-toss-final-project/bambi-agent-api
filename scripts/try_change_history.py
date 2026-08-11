"""변경점(Delta) 추적을 원하는 자료로 직접 돌려 본다 (개발 확인용).

"어제 대비 뭐가 바뀌었나"를 확인하려면 과거 팩트가 DB에 있어야 하는데, 웹
페이지(/changeHistory)는 그날 수집된 뉴스를 쓰므로 **값이 달라진 사실이 나온다는
보장이 없다.** 그래서 확인이 어렵다 — 시간이 지나야 하는 게 아니라, 원하는
변화를 만들어 넣을 수가 없는 것이다.

이 스크립트는 자료를 직접 넣어 그 자리에서 확인하게 해 준다. LLM은 실제로
호출하고 DB도 실제로 쓴다(전용 사용자로 격리한다).

실행:
    # 1일차 — 과거 팩트를 만든다
    uv run python scripts/try_change_history.py --day1 "코스닥이 3거래일 만에 21% 급등했다."

    # 2일차 — 값이 달라진 자료를 넣어 갱신이 잡히는지 본다
    uv run python scripts/try_change_history.py --day2 "코스닥이 4거래일 만에 28% 급등했다."

    # 저장된 과거 팩트만 확인
    uv run python scripts/try_change_history.py --show

    # 처음부터 다시
    uv run python scripts/try_change_history.py --reset

선행 조건:
- `AGENT_DATABASE_URL`과 `OPENAI_API_KEY`가 설정돼 있어야 한다(.env).
- `database/migrations/0012_change_history_delta.sql`이 적용돼 있어야 한다.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import selectors
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from agent.change_history.api import chg_001  # noqa: E402
from infrastructure.persistence.api import (  # noqa: E402
    list_change_history_facts,
    set_personal_wiki_scope,
)
from shared.report_models import ReportContextDocument  # noqa: E402

# 실제 사용자 데이터와 섞이지 않도록 전용 사용자로 격리한다.
DEFAULT_USER = "try-change-history"
DEFAULT_TOPIC = "델타 추적 수동 확인"


def build_context(text: str, reference: str = "G1") -> ReportContextDocument:
    """입력한 문장을 오늘 수집된 근거 문서 한 건처럼 만든다."""
    return ReportContextDocument(
        reference=reference,
        document_version_id=f"try-{reference}",
        chunk_id=f"try-chunk-{reference}",
        namespace_key="global",
        title=text[:40],
        content=text,
        url=None,
        score=1.0,
    )


async def show_facts(connection: Any, *, user_id: str, topic: str) -> None:
    """지금 저장돼 있는 과거 팩트를 보여준다(다음 실행의 대조 대상)."""
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        facts = await list_change_history_facts(
            connection, user_id=user_id, topic=topic
        )
    if not facts:
        print("저장된 과거 팩트가 없습니다 (다음 실행은 '첫 실행'으로 처리됩니다).")
        return
    print(f"저장된 과거 팩트 {len(facts)}건 — 다음 실행이 이것과 대조합니다:")
    for fact in facts:
        print(f"  · {fact.subject} / {fact.attribute} = {fact.fact_value}")


async def reset(connection: Any, *, user_id: str) -> None:
    """이 확인용 사용자의 델타 데이터를 전부 지운다."""
    async with connection.transaction():
        await connection.execute(
            "UPDATE agent.change_history_facts SET supersedes_fact_id = NULL "
            "WHERE user_id = %s",
            (user_id,),
        )
        await connection.execute(
            "DELETE FROM agent.change_history_facts WHERE user_id = %s", (user_id,)
        )
        await connection.execute(
            "DELETE FROM agent.change_history_runs WHERE user_id = %s", (user_id,)
        )
    print(f"'{user_id}'의 델타 데이터를 지웠습니다.")


async def run_day(
    connection: Any,
    *,
    user_id: str,
    topic: str,
    articles: list[str],
    reference_date: date,
    model: str,
) -> None:
    """오늘 자료로 델타 경로를 한 번 돌리고 판정 결과를 보여준다."""
    contexts = [
        build_context(text, f"G{index}")
        for index, text in enumerate(articles, start=1)
    ]
    print(f"\n[{reference_date}] 자료 {len(contexts)}건으로 실행합니다...")
    result = await chg_001(
        connection,
        user_id=user_id,
        job_id="try-change-history",
        topic=topic,
        contexts=contexts,
        model=model,
        reference_date=reference_date,
    )

    if result["is_first_run"]:
        print("→ 첫 실행입니다(대조할 과거 팩트가 없어 전부 신규로 처리).")
    if result["no_change"]:
        print("→ 이번엔 달라진 점이 없습니다. 요약 보고서는 정상적으로 나갑니다.")

    facts = result["facts"]
    print(f"\n판정 결과 ({len(facts)}건):")
    for item in facts:
        fact = item.fact
        if fact.verdict == "updated":
            print(f"  🔁 갱신  {fact.subject} / {fact.attribute}")
            print(f"        이전(DB에서 읽음): {item.before_value}")
            print(f"        오늘             : {fact.fact_value}")
        else:
            print(f"  🆕 신규  {fact.subject} / {fact.attribute} = {fact.fact_value}")
    if int(result["duplicate_count"]):
        print(f"  ♻️ 중복 {result['duplicate_count']}건 (보고서에 쓰지 않음)")
    print(f"\n저장된 팩트 {result['stored_fact_count']}건 — 다음 실행의 대조 대상이 됩니다.")


async def main_async(args: argparse.Namespace) -> int:
    """인자에 따라 조회·초기화·실행 중 하나를 수행한다."""
    dsn = os.getenv("AGENT_DATABASE_URL", "").strip()
    if not dsn:
        print("AGENT_DATABASE_URL이 없습니다. 로컬은 `docker compose up -d`로 띄웁니다.")
        return 2

    async with await psycopg.AsyncConnection.connect(
        dsn, row_factory=dict_row
    ) as connection:
        if args.reset:
            await reset(connection, user_id=args.user)
            return 0
        if args.show:
            await show_facts(connection, user_id=args.user, topic=args.topic)
            return 0

        today = datetime.now(UTC).date()
        if args.day1:
            # 1일차는 하루 전 날짜로 기록해 2일차와 시점이 구분되게 한다.
            await show_facts(connection, user_id=args.user, topic=args.topic)
            await run_day(
                connection,
                user_id=args.user,
                topic=args.topic,
                articles=args.day1,
                reference_date=today - timedelta(days=1),
                model=args.model,
            )
            return 0
        if args.day2:
            await show_facts(connection, user_id=args.user, topic=args.topic)
            await run_day(
                connection,
                user_id=args.user,
                topic=args.topic,
                articles=args.day2,
                reference_date=today,
                model=args.model,
            )
            return 0

    print("--day1 / --day2 / --show / --reset 중 하나를 지정하세요. (-h 참고)")
    return 2


def main() -> int:
    """명령행 인자를 읽어 실행한다."""
    parser = argparse.ArgumentParser(
        description="변경점 추적을 원하는 자료로 직접 돌려 본다."
    )
    parser.add_argument(
        "--day1", nargs="*", metavar="문장", help="1일차 자료(과거 팩트를 만든다)"
    )
    parser.add_argument(
        "--day2", nargs="*", metavar="문장", help="2일차 자료(갱신이 잡히는지 본다)"
    )
    parser.add_argument("--show", action="store_true", help="저장된 과거 팩트만 조회")
    parser.add_argument("--reset", action="store_true", help="확인용 데이터 초기화")
    parser.add_argument("--user", default=DEFAULT_USER, help="확인용 사용자 ID")
    parser.add_argument("--topic", default=DEFAULT_TOPIC, help="확인용 주제")
    parser.add_argument("--model", default="gpt-4.1-mini")
    args = parser.parse_args()

    return asyncio.run(
        main_async(args),
        loop_factory=(
            (lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
            if sys.platform == "win32"
            else None
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
