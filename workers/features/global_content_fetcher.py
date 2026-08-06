"""PostgreSQL Global 본문 수집 Worker (Jina Reader·YouTube 자막).

Global Source Collector가 수집 캐시(`global_source_documents`)에 저장한 문서
URL 중 아직 본문이 없는(`content_status='pending'`) 문서를 점유해 본문을 채운다.
문서별로 독립적인 Transaction과 오류 처리를 사용해 한 URL의 실패가 다른
URL의 저장을 되돌리지 않는다.

본문을 가져오는 방법은 Provider에 따라 다르다:

- 뉴스·Reddit: Jina Reader(r.jina.ai)로 페이지 본문을 정제해 가져온다. Reddit은
  게시글 본문이 페이지에 그대로 있어 뉴스와 같은 방식으로 충분하다(2026-07-29
  실측: 저장된 게시글 텍스트가 Jina 결과에 그대로 포함).
- YouTube: 영상 페이지라 Jina로는 "Skip navigation", "Sign in" 같은 UI 문구만
  나온다(같은 날 실측: 본문 17,466자 전부 UI). 대신 자막을 본문으로 쓴다.
  자막이 없거나 너무 짧은 영상은 실패로 남겨 빈 본문이 풀에 쌓이지 않게 한다.

처리는 **내려받기(병렬)와 저장(순차)** 두 단계로 나눈다. 소요 시간의 대부분이
외부 응답 대기라 내려받기를 겹치면 Batch 하나가 걸리는 시간이 크게 준다. 반면
저장은 겹칠 수 없다 — psycopg Connection 하나를 동시에 쓰면 프로토콜이 깨진다.
그래서 본문은 한꺼번에 받아 두고 DB 쓰기만 차례로 처리한다.
"""

import asyncio
import os
from asyncio import to_thread
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from agent.assistant.api import fetch_transcript, video_id_from_url
from infrastructure.persistence.api import (
    GlobalArticleToFetch,
    claim_global_articles_for_fetch,
    mark_global_article_fetch_failed,
    save_fetched_article_content,
    set_system_job_scope,
)
from shared.fetch_guard import describe_blocked_fetch
from infrastructure.sources.connectors.api import (
    JinaReadError,
    JinaReadResult,
    fetch_url_via_jina,
)

type DictRow = dict[str, Any]
type UrlFetcher = Callable[[str], JinaReadResult]
type TranscriptFetcher = Callable[[str], str | None]


# 자막이 이 길이 미만이면 근거로 쓸 내용이 없다고 보고 버린다.
#
# 영상 길이(예: 60초 미만)로 자르지 않는 이유: 길이는 내용량의 나쁜 대리 지표다.
# 말이 빽빽한 40초 영상은 쓸모가 있고, 배경음악만 깔린 3분 영상은 자막이 비거나
# 무의미하다. 우리는 영상을 자막으로만 읽으므로 "읽을 게 있는가"를 직접 재는
# 편이 정확하다. 화면 텍스트로만 정보를 전달하는 영상도 여기서 함께 걸러진다.
DEFAULT_MIN_TRANSCRIPT_CHARS = 500

# 동시에 내려받을 문서 수. Batch 크기(limit)와는 별개다 — limit이 20이고 이 값이
# 5면 5건씩 네 묶음으로 나눠 받는다.
#
# 무제한으로 열지 않는 이유는 외부 Rate Limit 때문이다. Jina Reader는 짧은 간격
# 대량 호출에 429를 돌려주고, 그렇게 실패한 문서는 `failed`로 남아 재시도 대상에서
# 빠진다. 처리량을 올리려다 문서를 잃는 쪽이 더 나쁘다.
DEFAULT_FETCH_CONCURRENCY = 5


def _fetch_concurrency() -> int:
    """동시 내려받기 수를 환경변수에서 읽는다. 형식이 틀리면 기본값."""
    try:
        return max(int(os.environ["GLOBAL_CONTENT_FETCH_CONCURRENCY"]), 1)
    except (KeyError, ValueError):
        return DEFAULT_FETCH_CONCURRENCY


@dataclass(frozen=True, slots=True)
class _DownloadedBody:
    """내려받기 단계의 결과. 본문이 있거나 실패 사유가 있다.

    이 단계는 DB를 건드리지 않는다. 저장·실패 표시는 호출자가 순차로 처리한다.
    """

    resolved_url: str | None = None
    title: str | None = None
    markdown: str | None = None
    published_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def failed(self) -> bool:
        """내려받기에 실패했는지 여부."""
        return self.error_code is not None


def _min_transcript_chars() -> int:
    """본문으로 인정할 자막 최소 길이를 환경변수에서 읽는다. 형식이 틀리면 기본값."""
    try:
        return max(int(os.environ["YOUTUBE_MIN_TRANSCRIPT_CHARS"]), 0)
    except (KeyError, ValueError):
        return DEFAULT_MIN_TRANSCRIPT_CHARS


def _parse_published_at(value: str | None) -> datetime | None:
    """Jina Reader의 게시 시각 문자열을 timezone 포함 datetime으로 변환한다."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def _mark_failed(
    connection: AsyncConnection[DictRow],
    *,
    article: GlobalArticleToFetch,
    error_code: str,
    error_message: str,
) -> dict[str, object]:
    """본문 수집에 실패한 문서를 실패로 표시하고 결과 항목을 만든다."""
    async with connection.transaction():
        await set_system_job_scope(connection)
        await mark_global_article_fetch_failed(
            connection,
            document_id=article.document_id,
            error_code=error_code,
            error_message=error_message,
        )
    return {
        "document_id": article.document_id,
        "url": article.url,
        "status": "failed",
        "error_code": error_code,
    }


async def _download_youtube_transcript(
    article: GlobalArticleToFetch, *, transcript_fetcher: TranscriptFetcher
) -> _DownloadedBody:
    """YouTube 영상 자막을 본문으로 내려받는다.

    자막이 없는 영상은 본문을 만들 방법이 없으므로 실패로 돌려준다. UI 문구를
    본문인 척 저장하면 이후 검색·생성이 그 문서를 근거로 쓰게 된다. 자막이
    있어도 근거로 쓰기에 너무 짧으면 같은 이유로 실패로 돌려준다.
    """
    video_id = video_id_from_url(article.url)
    if not video_id:
        return _DownloadedBody(
            error_code="YOUTUBE_INVALID_URL",
            error_message=f"영상 ID를 찾을 수 없습니다: {article.url}",
        )
    transcript = await to_thread(transcript_fetcher, video_id)
    if not transcript:
        return _DownloadedBody(
            error_code="YOUTUBE_NO_TRANSCRIPT",
            error_message="자막이 없어 본문을 만들 수 없습니다.",
        )
    minimum_chars = _min_transcript_chars()
    if len(transcript.strip()) < minimum_chars:
        return _DownloadedBody(
            error_code="YOUTUBE_TRANSCRIPT_TOO_SHORT",
            error_message=(
                f"자막이 {len(transcript.strip())}자로 최소 {minimum_chars}자에 "
                "못 미쳐 근거로 쓸 수 없습니다."
            ),
        )
    # 자막 저장은 제목을 주지 않는다 — 수집 때 저장한 영상 제목을 덮어쓰지 않기
    # 위해서다(save_fetched_article_content의 COALESCE 참고).
    return _DownloadedBody(resolved_url=article.url, markdown=transcript)


async def _download_one(
    article: GlobalArticleToFetch,
    *,
    url_fetcher: UrlFetcher,
    transcript_fetcher: TranscriptFetcher,
) -> _DownloadedBody:
    """문서 하나의 본문을 Provider에 맞는 방법으로 내려받는다.

    DB를 건드리지 않으므로 여러 건을 동시에 실행해도 안전하다. 예외를 밖으로
    던지지 않고 실패 사유로 감싸 돌려준다 — 한 문서의 실패가 같은 Batch의 다른
    문서 내려받기를 취소하면 안 되기 때문이다.
    """
    if article.provider == "youtube":
        return await _download_youtube_transcript(
            article, transcript_fetcher=transcript_fetcher
        )
    try:
        fetched = await to_thread(url_fetcher, article.url)
    except JinaReadError as error:
        return _DownloadedBody(
            error_code=f"JINA_{error.error_code.upper()}",
            error_message=str(error),
        )
    # 봇 차단 안내 페이지는 본문이 아니다. 저장하면 검색에 걸리고 리포트 근거로도
    # 들어간다(2026-08-06 실측: Cloudflare "Just a moment..." 페이지가 정상 본문으로
    # 저장돼 Wiki 노드까지 만들어졌다). Jina는 200을 주므로 여기서 따로 걸러야 한다.
    blocked = describe_blocked_fetch(fetched.title, fetched.markdown)
    if blocked is not None:
        return _DownloadedBody(error_code="FETCH_BLOCKED", error_message=blocked)
    return _DownloadedBody(
        resolved_url=fetched.resolved_url,
        title=fetched.title,
        markdown=fetched.markdown,
        published_at=_parse_published_at(fetched.published_time),
    )


async def _download_all(
    articles: list[GlobalArticleToFetch],
    *,
    url_fetcher: UrlFetcher,
    transcript_fetcher: TranscriptFetcher,
) -> list[_DownloadedBody]:
    """점유한 문서들의 본문을 동시에 내려받는다.

    동시 실행 수는 `GLOBAL_CONTENT_FETCH_CONCURRENCY`로 제한한다. 결과는 입력
    순서를 그대로 지켜, 호출자가 문서와 짝지어 저장할 수 있게 한다.
    """
    limiter = asyncio.Semaphore(_fetch_concurrency())

    async def _guarded(article: GlobalArticleToFetch) -> _DownloadedBody:
        """동시 실행 수 제한 안에서 문서 하나를 내려받는다."""
        async with limiter:
            return await _download_one(
                article,
                url_fetcher=url_fetcher,
                transcript_fetcher=transcript_fetcher,
            )

    return list(await asyncio.gather(*(_guarded(a) for a in articles)))


async def _persist_one(
    connection: AsyncConnection[DictRow],
    *,
    article: GlobalArticleToFetch,
    body: _DownloadedBody,
) -> dict[str, object]:
    """내려받은 본문을 저장하거나 실패로 표시한다.

    Connection 하나를 쓰므로 호출자가 반드시 순차로 부른다.
    """
    if body.failed:
        return await _mark_failed(
            connection,
            article=article,
            error_code=str(body.error_code),
            error_message=str(body.error_message or ""),
        )
    async with connection.transaction():
        await set_system_job_scope(connection)
        saved = await save_fetched_article_content(
            connection,
            document_id=article.document_id,
            resolved_url=body.resolved_url,
            title=body.title,
            markdown=body.markdown,
            published_at=body.published_at,
        )
    return {"url": article.url, "status": "completed", **saved}


async def run_global_content_fetch_batch(
    *,
    database_url: str,
    limit: int = 5,
    url_fetcher: UrlFetcher = fetch_url_via_jina,
    transcript_fetcher: TranscriptFetcher = fetch_transcript,
) -> list[dict[str, object]]:
    """본문이 없는 Global 문서 Batch를 점유해 Provider에 맞게 본문을 채운다.

    본문 내려받기는 동시에, DB 저장은 순차로 처리한다(모듈 상단 주석 참고).

    Args:
        database_url: Agent DB 연결 문자열
        limit: 한 번에 처리할 최대 문서 수
        url_fetcher: URL 본문 수집기 (테스트에서 네트워크 대체용)
        transcript_fetcher: YouTube 자막 수집기 (테스트에서 네트워크 대체용)

    Returns:
        문서별 본문 수집 결과 또는 실패 정보 목록. 점유한 문서 순서를 지킨다
    """
    connection: AsyncConnection[DictRow] = await AsyncConnection.connect(
        database_url,
        row_factory=dict_row,
    )
    try:
        async with connection.transaction():
            await set_system_job_scope(connection)
            articles = await claim_global_articles_for_fetch(connection, limit=limit)
        if not articles:
            return []
        bodies = await _download_all(
            articles,
            url_fetcher=url_fetcher,
            transcript_fetcher=transcript_fetcher,
        )
        results: list[dict[str, object]] = []
        for article, body in zip(articles, bodies, strict=True):
            results.append(
                await _persist_one(connection, article=article, body=body)
            )
        return results
    finally:
        await connection.close()
