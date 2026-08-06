"""이미 수집된 Global 문서의 검색 색인용 본문(search_body)을 채운다.

마이그레이션 0012로 색인 대상이 `markdown`(페이지 통짜)에서 `search_body`
(기사 본문)로 바뀌었다. 기존 문서는 `search_body`가 비어 있어 COALESCE로
원문을 계속 보고 있으므로, 이 스크립트로 채워야 정제 효과가 난다.

**재수집하지 않는다.** 원문이 이미 DB에 있으므로 읽어서 정제해 옆 칸에 넣기만
한다. 외부 호출도 LLM 호출도 없다.

실행:
    uv run python scripts/backfill_search_body.py            # 미리보기
    uv run python scripts/backfill_search_body.py --apply    # 실제 저장
"""

from __future__ import annotations

import argparse
import asyncio
import os
import selectors
import sys
from pathlib import Path

# scripts/ 를 직접 실행해도 저장소 모듈을 찾도록 한다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row

from shared.search_text import build_search_body

# 한 번에 읽어 처리할 문서 수. 원문이 문서당 수만 자라 통째로 읽으면 메모리를 먹는다.
_BATCH_SIZE = 200


async def _fill_batch(
    connection: AsyncConnection[DictRow], *, apply: bool
) -> tuple[int, int, int]:
    """search_body가 빈 문서 한 배치를 정제한다.

    Returns:
        (읽은 수, 채운 수, 원문 총 길이 - 정제본 총 길이)
    """
    cursor = await connection.execute(
        """
        SELECT id, title, markdown
        FROM agent.global_source_documents
        WHERE search_body IS NULL
          AND markdown IS NOT NULL
          AND content_status = 'fetched'
        ORDER BY updated_at DESC
        LIMIT %s
        """,
        (_BATCH_SIZE,),
    )
    rows = await cursor.fetchall()
    if not rows:
        return 0, 0, 0

    filled = 0
    saved_chars = 0
    for row in rows:
        body = build_search_body(row["markdown"], title=str(row["title"] or ""))
        if body is None:
            # 정제 결과가 비면 건드리지 않는다 — COALESCE가 원문을 계속 본다.
            continue
        saved_chars += len(row["markdown"]) - len(body)
        filled += 1
        if apply:
            await connection.execute(
                "UPDATE agent.global_source_documents SET search_body = %s WHERE id = %s",
                (body, row["id"]),
            )
    return len(rows), filled, saved_chars


async def main() -> int:
    """빈 문서가 없을 때까지 배치를 반복한다."""
    parser = argparse.ArgumentParser(description="search_body 백필")
    parser.add_argument(
        "--apply", action="store_true", help="실제로 저장한다(생략하면 미리보기)"
    )
    args = parser.parse_args()

    database_url = os.environ.get("AGENT_DATABASE_URL")
    if not database_url:
        print("AGENT_DATABASE_URL이 필요합니다.", file=sys.stderr)
        return 1

    connection = await AsyncConnection.connect(database_url, row_factory=dict_row)
    total_read = 0
    total_filled = 0
    total_saved = 0
    try:
        while True:
            async with connection.transaction():
                read, filled, saved = await _fill_batch(connection, apply=args.apply)
            if read == 0:
                break
            total_read += read
            total_filled += filled
            total_saved += saved
            print(f"  {total_filled:,}건 처리…", flush=True)
            # 미리보기는 저장하지 않으므로 같은 배치를 무한히 다시 읽는다.
            if not args.apply:
                break
    finally:
        await connection.close()

    mode = "저장 완료" if args.apply else "미리보기(저장 안 함)"
    print(f"\n{mode}")
    print(f"  대상 {total_read:,}건 중 {total_filled:,}건 정제")
    if total_filled:
        print(f"  색인 텍스트 {total_saved:,}자 감소 (문서당 평균 {total_saved // total_filled:,}자)")
    if not args.apply:
        print("\n실제로 저장하려면 --apply 를 붙이세요.")
    return 0


if __name__ == "__main__":
    # psycopg async 모드는 Windows 기본 ProactorEventLoop를 지원하지 않는다.
    loop_factory = (
        (lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
        if sys.platform == "win32"
        else None
    )
    raise SystemExit(asyncio.run(main(), loop_factory=loop_factory))
