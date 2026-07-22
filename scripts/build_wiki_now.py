""""지금 Wiki에 반영" 강제 실행 진입점.

조용 시간(quiet window) 정책으로 미뤄져 있는 사용자의 personal_wiki_build
Job 전체를 즉시 실행 가능 상태로 되돌리고(SCH-009 release), Personal Wiki
Builder Worker Batch를 대기 Job이 없어질 때까지 반복 실행한다.

실행: uv run python scripts/build_wiki_now.py [--user-id <id>] [--limit <n>]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.config import load_settings
from infrastructure.persistence.api import set_personal_wiki_scope
from scheduler.api import sch_009
from workers.api import run_personal_wiki_batch

type DictRow = dict[str, Any]

DEFAULT_USER_ID = "mock-clipping-user"
MAX_BATCH_ROUNDS = 20


async def release_pending_jobs(database_url: str, user_id: str) -> int:
    """SCH-009 release로 사용자의 대기 Job을 즉시 실행 가능하게 만든다."""
    connection: AsyncConnection[DictRow] = await AsyncConnection.connect(
        database_url, row_factory=dict_row
    )
    try:
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=user_id)
            result = await sch_009(
                connection,
                user_id=user_id,
                action="release",
            )
    finally:
        await connection.close()
    return result.affected_jobs


async def run_until_drained(
    *,
    database_url: str,
    user_id: str,
    limit: int,
    lease_seconds: int,
    model: str,
    embedding_model: str,
) -> list[dict[str, object]]:
    """대기 Job이 없어질 때까지 Worker Batch를 반복 실행한다."""
    released = await release_pending_jobs(database_url, user_id)
    print(f"즉시 실행으로 전환된 Job: {released}건")
    all_results: list[dict[str, object]] = []
    for _ in range(MAX_BATCH_ROUNDS):
        results = await run_personal_wiki_batch(
            database_url=database_url,
            worker_id=f"build-wiki-now-{user_id}",
            limit=limit,
            lease_seconds=lease_seconds,
            model=model,
            embedding_model=embedding_model,
        )
        if not results:
            break
        all_results.extend(results)
    return all_results


def main() -> int:
    """CLI 인자를 해석하고 강제 Wiki Build를 실행한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--limit", type=int, help="Batch당 Claim할 최대 Job 수")
    parser.add_argument("--lease-seconds", type=int, help="Job Lease 유지 시간")
    args = parser.parse_args()

    settings = load_settings()
    if not settings.agent_database_url:
        print("AGENT_DATABASE_URL이 설정되지 않았습니다.", file=sys.stderr)
        return 2

    # Windows의 psycopg 비동기 연결은 Proactor Loop를 지원하지 않는다.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        results = runner.run(
            run_until_drained(
                database_url=settings.agent_database_url,
                user_id=args.user_id,
                limit=args.limit or settings.personal_wiki_worker_batch_size,
                lease_seconds=(
                    args.lease_seconds or settings.personal_wiki_job_lease_seconds
                ),
                model=settings.wiki_llm_model,
                embedding_model=settings.wiki_embedding_model,
            )
        )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    failures = sum(1 for result in results if result.get("status") != "completed")
    print(f"\n총 {len(results)}건 처리, 실패 {failures}건")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
