"""로컬 Obsidian 클리핑(.md)을 Jina 재수집 없이 Agent DB 원본 테이블에 직접 적재한다.

`scripts/ingest_user_urls.py`는 URL을 Jina Reader로 실시간 재수집하지만, 이 스크립트는
이미 손에 있는 클리핑 Markdown 본문을 그대로 원본 Version으로 저장한다(죽은 링크·재수집
비용·본문 변형 회피). frontmatter의 title·final_url/source를 문서 식별 정보로 쓰고,
`---` 프론트매터를 제거한 본문을 raw_content로 저장한다.

같은 persistence 함수(register_user_url_source / save_user_url_document_version /
enqueue_personal_wiki_build_job)를 재사용하므로 이후 build_wiki_now 경로가 그대로 동작한다.
모델 비교를 위해 같은 클리핑 셋을 서로 다른 user-id로 여러 번 적재할 수 있다.

실행:
  uv run python scripts/model_wiki_eval/ingest_local_clippings.py \
      --user-id model-eval-4o-mini --clippings-dir <경로>
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.config import load_settings
from infrastructure.persistence.api import (
    defer_user_wiki_build_jobs,
    enqueue_personal_wiki_build_job,
    mark_url_source_event,
    register_user_url_source,
    save_user_url_document_version,
    set_personal_wiki_scope,
)

type DictRow = dict[str, Any]

_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)


def make_source_event_id(url: str) -> str:
    """URL로 재실행해도 같은 값이 나오는 멱등 이벤트 식별자를 만든다."""
    return f"local-clip-{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}"


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """클리핑 Markdown에서 frontmatter 키·값과 본문을 분리한다.

    Args:
        text: 클리핑 파일 전체 내용

    Returns:
        (frontmatter 딕셔너리, 프론트매터를 제거한 본문 Markdown)
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    block = match.group(1)
    body = text[match.end() :]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        kv = re.match(r'^([A-Za-z0-9_]+):\s*"?(.*?)"?\s*$', line)
        if kv:
            fields[kv.group(1)] = kv.group(2)
    return fields, body


def parse_published_time(value: str | None) -> datetime | None:
    """ISO8601 게시 시각 문자열을 datetime으로 변환한다. 실패 시 None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def ingest_clipping(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    path: Path,
    quiet_minutes: int,
    max_wait_minutes: int,
) -> str:
    """클리핑 파일 하나를 원본 문서 Version으로 등록·저장하고 결과 요약을 반환한다.

    URL을 canonical 식별 정보로 쓰고, 프론트매터를 제거한 본문을 raw_content로
    저장한다. 새 Version이 저장되면 같은 트랜잭션에서 personal_wiki_build Job을
    멱등 등록하고 조용 시간 정책으로 미룬다(build_wiki_now가 나중에 release).
    """
    text = path.read_text(encoding="utf-8")
    fields, body = parse_frontmatter(text)
    url = fields.get("final_url") or fields.get("source")
    if not url:
        return f"skipped (URL 없음: {path.name})"
    title = fields.get("title") or path.stem
    published_at = parse_published_time(fields.get("published"))

    source_event_id = make_source_event_id(url)
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        registered = await register_user_url_source(
            connection,
            user_id=user_id,
            url=url,
            source_event_id=source_event_id,
        )

    try:
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=user_id)
            saved = await save_user_url_document_version(
                connection,
                user_id=user_id,
                source_document_id=registered.source_document_id,
                source_event_row_id=registered.source_event_row_id,
                title=title,
                raw_content=body,
                resolved_url=url,
                published_at=published_at,
            )
            enqueued = None
            if saved is not None:
                enqueued = await enqueue_personal_wiki_build_job(
                    connection,
                    user_id=user_id,
                    source_document_id=registered.source_document_id,
                    source_document_version_id=saved.source_version_id,
                    source_version=saved.version,
                    source_event_id=source_event_id,
                    source_event_row_id=registered.source_event_row_id,
                )
                await defer_user_wiki_build_jobs(
                    connection,
                    user_id=user_id,
                    quiet_minutes=quiet_minutes,
                    max_wait_minutes=max_wait_minutes,
                )
            await mark_url_source_event(
                connection,
                source_event_row_id=registered.source_event_row_id,
                status="completed",
            )
    except Exception as error:  # 저장 실패도 Version 없이 이벤트에만 기록한다.
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=user_id)
            await mark_url_source_event(
                connection,
                source_event_row_id=registered.source_event_row_id,
                status="failed",
                error_code="persistence_error",
                error_message=str(error)[:500],
            )
        return f"failed (persistence_error: {error})"

    if saved is None:
        return "unchanged (동일 content_hash, 새 Version 생략)"
    job_note = (
        f", wiki job {'등록' if enqueued.created else '재사용'} {enqueued.job_id}"
        if enqueued is not None
        else ""
    )
    return f"saved (version {saved.version}, {len(body)} chars{job_note})"


async def run(
    user_id: str,
    clippings_dir: Path,
    database_url: str,
    *,
    quiet_minutes: int,
    max_wait_minutes: int,
) -> int:
    """디렉터리의 모든 .md 클리핑을 순차 적재한다. 실패가 있으면 1을 반환한다."""
    files = sorted(clippings_dir.glob("*.md"))
    if not files:
        print(f"클리핑 파일이 없습니다: {clippings_dir}", file=sys.stderr)
        return 2
    connection: AsyncConnection[DictRow] = await AsyncConnection.connect(
        database_url, row_factory=dict_row
    )
    failures = 0
    saved = 0
    try:
        for path in files:
            summary = await ingest_clipping(
                connection,
                user_id=user_id,
                path=path,
                quiet_minutes=quiet_minutes,
                max_wait_minutes=max_wait_minutes,
            )
            if summary.startswith("failed") or summary.startswith("skipped"):
                failures += 1
            if summary.startswith("saved"):
                saved += 1
            print(f"- {path.name}\n  -> {summary}")
    finally:
        await connection.close()
    print(f"\n총 {len(files)}건 중 저장 {saved}건, 실패/스킵 {failures}건")
    return 1 if failures else 0


def main() -> int:
    """CLI 인자를 해석하고 로컬 클리핑 적재를 실행한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--clippings-dir", type=Path, required=True)
    args = parser.parse_args()

    settings = load_settings()
    if not settings.agent_database_url:
        print("AGENT_DATABASE_URL이 설정되지 않았습니다.", file=sys.stderr)
        return 2

    # Windows의 psycopg 비동기 연결은 Proactor Loop를 지원하지 않는다.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        return runner.run(
            run(
                args.user_id,
                args.clippings_dir,
                settings.agent_database_url,
                quiet_minutes=settings.wiki_build_quiet_minutes,
                max_wait_minutes=settings.wiki_build_max_wait_minutes,
            )
        )


if __name__ == "__main__":
    raise SystemExit(main())
