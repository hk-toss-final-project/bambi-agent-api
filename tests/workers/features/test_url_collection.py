"""사용자 URL 수집 Worker의 Jina 호출·저장·Job 완료 경로를 검증한다."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from infrastructure.persistence.api import ClaimedAgentJob
from infrastructure.sources.connectors.api import ArticleImageMetadata, JinaReadResult
from workers.features import url_collection

# 차단 감지기(shared.fetch_guard)가 짧은 본문을 수집 실패로 보므로,
# 픽스처도 실제 기사 정도의 길이를 갖는다.
_FETCHED_MARKDOWN = "# 수집 본문. " + "기사 본문 문장입니다. " * 30



class _FakeConnection:
    """URL Worker가 사용하는 Transaction 경계만 제공하는 연결 대역."""

    def __init__(self) -> None:
        """열린 Transaction 횟수를 0으로 초기화한다."""
        self.transactions = 0

    @asynccontextmanager
    async def transaction(self):
        """Transaction 진입 횟수를 기록하고 비어 있는 문맥을 제공한다."""
        self.transactions += 1
        yield


def _url_job(payload: dict[str, object] | None = None) -> ClaimedAgentJob:
    """테스트용 personal_wiki_url Job을 만든다."""
    return ClaimedAgentJob(
        job_id="url-job-1",
        user_id="user-1",
        feature_id="SVC-003",
        job_type="personal_wiki_url",
        attempt_number=1,
        max_attempts=3,
        payload=payload
        or {
            "url": "https://example.com/article",
            "source_document_id": "source-1",
            "source_event_id": "event-1",
            "source_event_row_id": "event-row-1",
        },
    )


def test_process_job_fetches_saves_and_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """URL Job이 Jina 본문 저장과 후속 Wiki Job 등록 결과로 완료되는지 검증한다."""
    connection = _FakeConnection()
    saved_kwargs: dict[str, Any] = {}
    completed: list[Any] = []

    async def fake_user_scope(conn: Any, *, user_id: str) -> None:
        """사용자 Scope 인자를 검증한다."""
        assert conn is connection
        assert user_id == "user-1"

    async def fake_system_scope(conn: Any) -> None:
        """시스템 Scope 연결을 검증한다."""
        assert conn is connection

    async def fake_save(conn: Any, **kwargs: Any) -> dict[str, object]:
        """본문 저장 인자를 기록하고 후속 Wiki Job 결과를 반환한다."""
        assert conn is connection
        saved_kwargs.update(kwargs)
        return {
            "source_document_id": "source-1",
            "source_document_version_id": "version-1",
            "wiki_build_job_id": "wiki-job-1",
            "unchanged": False,
        }

    async def fake_complete(conn: Any, command: Any) -> None:
        """완료 Command를 기록한다."""
        assert conn is connection
        completed.append(command)

    def fake_fetch(url: str) -> JinaReadResult:
        """외부 호출 없이 결정적인 Jina 결과를 반환한다."""
        assert url == "https://example.com/article"
        return JinaReadResult(
            requested_url=url,
            resolved_url="https://example.com/final",
            title="수집 제목",
            published_time="2026-08-04T09:30:00Z",
            markdown=_FETCHED_MARKDOWN,
        )

    monkeypatch.setattr(url_collection, "set_personal_wiki_scope", fake_user_scope)
    monkeypatch.setattr(url_collection, "set_system_job_scope", fake_system_scope)
    monkeypatch.setattr(url_collection, "save_fetched_url_and_enqueue", fake_save)
    monkeypatch.setattr(url_collection, "db_026", fake_complete)

    result = asyncio.run(
        url_collection._process_job(
            connection,  # type: ignore[arg-type]
            job=_url_job(),
            worker_id="url-worker-1",
            url_fetcher=fake_fetch,
            image_fetcher=lambda url: ArticleImageMetadata(
                url="https://cdn.example/personal-cover.jpg",
                source="open_graph",
            ),
        )
    )

    assert result["wiki_build_job_id"] == "wiki-job-1"
    assert saved_kwargs["markdown"] == _FETCHED_MARKDOWN
    assert saved_kwargs["resolved_url"] == "https://example.com/final"
    assert saved_kwargs["image_url"] == "https://cdn.example/personal-cover.jpg"
    assert saved_kwargs["published_at"] == datetime(2026, 8, 4, 9, 30, tzinfo=UTC)
    assert saved_kwargs["quiet_minutes"] == 0
    assert connection.transactions == 2
    assert completed[0].worker_id == "url-worker-1"
    assert completed[0].result == result


def test_process_job_rejects_missing_source_identifiers() -> None:
    """원본 식별자가 없는 URL Job을 외부 호출 전에 실패시키는지 검증한다."""
    connection = _FakeConnection()

    with pytest.raises(ValueError, match="원본 식별자"):
        asyncio.run(
            url_collection._process_job(
                connection,  # type: ignore[arg-type]
                job=_url_job({"url": "https://example.com"}),
                worker_id="url-worker-1",
                url_fetcher=lambda _: (_ for _ in ()).throw(
                    AssertionError("Jina를 호출하면 안 됩니다.")
                ),
            )
        )


def test_run_url_collection_batch_claims_only_url_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """URL Batch 실행기가 personal_wiki_url 유형과 재시도 오류 접두사를 전달하는지 검증한다."""
    recorded: dict[str, Any] = {}

    async def fake_batch(**kwargs: Any) -> list[dict[str, object]]:
        """공통 Batch 러너 인자를 기록한다."""
        recorded.update(kwargs)
        return [{"job_id": "url-job-1", "status": "completed"}]

    monkeypatch.setattr(url_collection, "run_job_batch", fake_batch)

    result = asyncio.run(
        url_collection.run_url_collection_batch(
            database_url="postgresql://test",
            worker_id="url-worker-1",
            limit=5,
            lease_seconds=120,
        )
    )

    assert result[0]["status"] == "completed"
    assert recorded["job_type"] == "personal_wiki_url"
    assert recorded["error_code_prefix"] == "URL_COLLECTION"
    assert recorded["limit"] == 5


def test_blocked_page_is_not_saved_as_wiki_source() -> None:
    """봇 차단 안내 페이지는 저장하지 않고 Job을 실패시킨다.

    실측(2026-08-06): 사용자가 나무위키 URL을 저장했더니 Cloudflare의
    "Just a moment..." 페이지가 본문으로 저장돼, LLM이 그것을 읽고
    "namu.wiki — 악성 봇으로부터 보호하기 위해 보안 서비스를 사용하는 웹사이트"
    라는 Wiki 노드를 만들었다. 수집도 Wiki 빌드도 성공으로 끝나 아무도 몰랐다.
    """
    from shared.fetch_guard import FetchBlockedError

    saved: list[dict[str, Any]] = []

    def blocked_fetcher(url: str) -> JinaReadResult:
        """Cloudflare 차단 응답을 재현한다. Jina는 200으로 돌려준다."""
        return JinaReadResult(
            requested_url=url,
            resolved_url=url,
            title="Just a moment...",
            published_time=None,
            markdown="Enable JavaScript and cookies to continue",
        )

    async def fake_save(*args: Any, **kwargs: Any) -> dict[str, object]:
        """저장이 호출되면 기록한다(호출되면 안 된다)."""
        saved.append(kwargs)
        return {}

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(url_collection, "save_fetched_url_and_enqueue", fake_save)
        with pytest.raises(FetchBlockedError):
            asyncio.run(
                url_collection._process_job(
                    _FakeConnection(),  # type: ignore[arg-type]
                    job=_url_job(),
                    worker_id="worker-1",
                    url_fetcher=blocked_fetcher,
                )
            )

    assert saved == []
