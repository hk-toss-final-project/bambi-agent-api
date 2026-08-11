"""사용자 URL 원문을 Jina Reader로 수집하는 PostgreSQL Worker.

Lease로 점유한 personal_wiki_url Job의 URL을 Jina Reader로 읽고 Markdown
원본 Version을 Agent DB에 저장한 뒤, 변경된 본문에 대해 Personal Wiki Build
Job을 등록한다.
"""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from psycopg import AsyncConnection

from domain.jobs.api import job_007
from infrastructure.persistence.api import (
    ClaimedAgentJob,
    CompleteAgentJobCommand,
    db_026,
    save_fetched_url_and_enqueue,
    set_personal_wiki_scope,
    set_system_job_scope,
)
from infrastructure.sources.connectors.api import JinaReadResult, fetch_url_via_jina
from shared.fetch_guard import ensure_fetch_is_readable
from workers.features.batch_runner import run_job_batch

type DictRow = dict[str, Any]
type UrlFetcher = Callable[[str], JinaReadResult]


def _parse_published_at(value: str | None) -> datetime | None:
    """Jina 게시 시각을 timezone 포함 datetime으로 변환하고 잘못된 값은 무시한다."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def _process_job(
    connection: AsyncConnection[DictRow],
    *,
    job: ClaimedAgentJob,
    worker_id: str,
    url_fetcher: UrlFetcher,
) -> dict[str, object]:
    """점유한 URL Job 하나를 Jina로 수집·저장하고 완료 상태로 바꾼다."""
    url = str(job.payload.get("url") or "").strip()
    source_document_id = str(job.payload.get("source_document_id") or "").strip()
    source_event_id = str(job.payload.get("source_event_id") or "").strip()
    source_event_row_id = str(job.payload.get("source_event_row_id") or "").strip()
    if not url:
        raise ValueError("URL 수집 Job Payload에 url이 없습니다.")
    if not source_document_id or not source_event_id or not source_event_row_id:
        raise ValueError("URL 수집 Job Payload에 원본 식별자가 없습니다.")

    fetched = await asyncio.to_thread(url_fetcher, url)
    # 차단 안내 페이지를 본문으로 저장하지 않는다. 저장하면 LLM이 그 안내문을
    # 읽고 엉뚱한 Wiki 노드를 만든다(2026-08-06 실측: 나무위키 URL이
    # "namu.wiki — 악성 봇으로부터 보호하기 위해 보안 서비스를 사용하는 웹사이트"
    # 노드를 만들었다. 원문은 Cloudflare의 "Just a moment..." 페이지였다).
    #
    # 여기서 예외를 올리면 Job이 실패로 기록돼 사용자가 원인을 볼 수 있다.
    # 조용히 성공시키는 것보다 낫다.
    ensure_fetch_is_readable(fetched.title, fetched.markdown)
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=job.user_id)
        result = await save_fetched_url_and_enqueue(
            connection,
            user_id=job.user_id,
            source_document_id=source_document_id,
            source_event_id=source_event_id,
            source_event_row_id=source_event_row_id,
            title=fetched.title,
            markdown=fetched.markdown,
            resolved_url=fetched.resolved_url,
            image_url=fetched.image_url,
            published_at=_parse_published_at(fetched.published_time),
        )

    linked_result = await job_007(result)
    async with connection.transaction():
        await set_system_job_scope(connection)
        await db_026(
            connection,
            CompleteAgentJobCommand(
                job=job,
                worker_id=worker_id,
                result=linked_result,
            ),
        )
    return linked_result


async def run_url_collection_batch(
    *,
    database_url: str,
    worker_id: str,
    limit: int = 1,
    lease_seconds: int = 600,
    url_fetcher: UrlFetcher = fetch_url_via_jina,
) -> list[dict[str, object]]:
    """대기 중인 사용자 URL 수집 Job Batch를 점유해 순차적으로 처리한다."""
    if not database_url:
        raise ValueError("URL 수집 Worker에 database_url이 필요합니다.")
    if not worker_id:
        raise ValueError("URL 수집 Worker에 worker_id가 필요합니다.")

    async def process(
        connection: AsyncConnection[DictRow], job: ClaimedAgentJob
    ) -> dict[str, object]:
        """공통 러너가 점유한 Job 하나를 Jina 수집 경로로 처리한다."""
        return await _process_job(
            connection,
            job=job,
            worker_id=worker_id,
            url_fetcher=url_fetcher,
        )

    return await run_job_batch(
        database_url=database_url,
        job_type="personal_wiki_url",
        worker_id=worker_id,
        limit=limit,
        lease_seconds=lease_seconds,
        concurrency=1,
        error_code_prefix="URL_COLLECTION",
        process=process,
    )
