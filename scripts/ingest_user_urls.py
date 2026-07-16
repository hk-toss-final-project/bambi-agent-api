"""사용자 입력 URL을 Jina Reader로 수집해 Agent DB 원본 테이블에 저장한다.

URL은 지속적인 식별 정보이므로 user_source_documents.canonical_url에 저장하고,
Jina Reader(r.jina.ai)로 읽은 Markdown 본문은 재수집 시 변경될 수 있는
스냅샷이므로 user_source_document_versions에 저장한다. content_hash가 이전
Version과 같으면 새 Version을 만들지 않고, 실패한 수집은 Version 대신
wiki_source_events에 failed 상태와 오류로 기록한다.

새 Version을 저장하면 같은 Transaction에서 personal_wiki_build Job을 멱등
등록하고(SVC-003, JOB-001), 사용자의 대기 Job 전체 실행 시각을 조용 시간
정책(SCH-009: 마지막 수집 + WIKI_BUILD_QUIET_MINUTES, 상한 첫 대기 Job +
WIKI_BUILD_MAX_WAIT_MINUTES)으로 미룬다. Worker는 그 시각 이후에만 Job을
Claim해 개인 Wiki 문서로 반영한다.

기본 입력은 dummy/urls/url.txt이며 --url을 지정하면 해당 URL만 수집한다.

실행: uv run python scripts/ingest_user_urls.py [--user-id <id>] [--url <url> ...]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
from infrastructure.sources.connectors.api import JinaReadError, fetch_url_via_jina
from scripts.user_url_file import load_user_urls

type DictRow = dict[str, Any]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL_FILE = PROJECT_ROOT / "dummy" / "urls" / "url.txt"
DEFAULT_USER_ID = "mock-clipping-user"


def make_source_event_id(url: str) -> str:
    """URL로 재실행해도 같은 값이 나오는 멱등 이벤트 식별자를 만든다."""
    return f"user-url-{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}"


def parse_published_time(value: str | None) -> datetime | None:
    """Jina Reader의 게시 시각 문자열을 datetime으로 변환한다. 실패 시 None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def ingest_url(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    url: str,
    quiet_minutes: int,
    max_wait_minutes: int,
) -> str:
    """URL 하나를 등록·수집·저장하고 처리 결과 요약 문자열을 반환한다.

    등록과 저장은 각각 별도 트랜잭션으로 처리해 한 URL의 실패가
    다른 URL의 저장에 영향을 주지 않게 한다. 새 Version을 저장하면
    같은 트랜잭션에서 사용자의 대기 Wiki Build Job 전체를 조용 시간
    정책(SCH-009)으로 미룬다.
    """
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
        result = await asyncio.to_thread(fetch_url_via_jina, url)
    except JinaReadError as error:
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=user_id)
            await mark_url_source_event(
                connection,
                source_event_row_id=registered.source_event_row_id,
                status="failed",
                error_code=error.error_code,
                error_message=str(error),
            )
        return f"failed ({error.error_code})"

    try:
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=user_id)
            saved = await save_user_url_document_version(
                connection,
                user_id=user_id,
                source_document_id=registered.source_document_id,
                source_event_row_id=registered.source_event_row_id,
                title=result.title,
                raw_content=result.markdown,
                resolved_url=result.resolved_url,
                published_at=parse_published_time(result.published_time),
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
    return f"saved (version {saved.version}, {len(result.markdown)} chars{job_note})"


async def run(
    user_id: str,
    urls: list[str],
    database_url: str,
    *,
    quiet_minutes: int,
    max_wait_minutes: int,
) -> int:
    """모든 URL을 순차 수집하고 결과를 출력한다. 실패가 있으면 1을 반환한다."""
    connection: AsyncConnection[DictRow] = await AsyncConnection.connect(
        database_url, row_factory=dict_row
    )
    failures = 0
    try:
        for url in urls:
            summary = await ingest_url(
                connection,
                user_id=user_id,
                url=url,
                quiet_minutes=quiet_minutes,
                max_wait_minutes=max_wait_minutes,
            )
            if summary.startswith("failed"):
                failures += 1
            print(f"- {url}\n  -> {summary}")
    finally:
        await connection.close()
    print(f"\n총 {len(urls)}건 중 실패 {failures}건")
    return 1 if failures else 0


def main() -> int:
    """CLI 인자를 해석하고 URL 수집을 실행한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument(
        "--url",
        action="append",
        dest="urls",
        help="수집할 URL. 생략하면 --url-file의 목록을 사용한다.",
    )
    parser.add_argument(
        "--url-file",
        type=Path,
        default=DEFAULT_URL_FILE,
        help="--url을 생략했을 때 읽을 URL 목록 파일.",
    )
    args = parser.parse_args()

    settings = load_settings()
    if not settings.agent_database_url:
        print("AGENT_DATABASE_URL이 설정되지 않았습니다.", file=sys.stderr)
        return 2

    urls = args.urls or load_user_urls(args.url_file)
    # Windows의 psycopg 비동기 연결은 Proactor Loop를 지원하지 않는다.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        return runner.run(
            run(
                args.user_id,
                urls,
                settings.agent_database_url,
                quiet_minutes=settings.wiki_build_quiet_minutes,
                max_wait_minutes=settings.wiki_build_max_wait_minutes,
            )
        )


if __name__ == "__main__":
    raise SystemExit(main())
