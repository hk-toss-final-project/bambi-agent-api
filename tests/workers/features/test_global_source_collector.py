"""Global Source Collector Worker의 수집·저장·격리 동작을 검증한다.

실제 DB·네트워크 없이 Connection과 Provider를 대역으로 주입해, Provider별
실패 격리와 pending 저장 흐름을 확인한다.
"""

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Any

import pytest

import workers.features.global_source_collector as collector
from infrastructure.sources.connectors.api import (
    GoogleNewsRssProvider,
    GdeltNewsProvider,
    LatestArticle,
    LatestProviderError,
    NaverNewsProvider,
    NewsApiProvider,
    RedditSearchProvider,
    YouTubeSearchProvider,
)


class _FakeCursor:
    """순서별 Row를 반환하는 Cursor Test Double."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        """첫 번째 Row나 None을 반환한다."""
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        """전체 Row 목록을 반환한다."""
        return self._rows


class _FakeConnection:
    """execute 순서별 응답과 transaction·close를 흉내 내는 Connection 대역."""

    def __init__(self, responses: list[list[dict[str, Any]]]) -> None:
        self._responses = responses
        self.executed: list[str] = []
        self.closed = False

    async def execute(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> _FakeCursor:
        """SQL을 기록하고 순서별 Cursor를 반환한다."""
        self.executed.append(query)
        rows = self._responses.pop(0) if self._responses else []
        return _FakeCursor(rows)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """psycopg transaction 문맥을 흉내 낸다."""
        yield

    async def close(self) -> None:
        """연결 종료를 기록한다."""
        self.closed = True


class _OneArticleProvider:
    """기사 한 건을 반환하는 Provider 대역."""

    def __init__(self, name: str) -> None:
        self.name = name

    async def search(
        self, *, query: str, limit: int, language: str | None
    ) -> list[LatestArticle]:
        """검색 Query를 반영한 기사 한 건을 반환한다."""
        return [
            LatestArticle(
                provider=self.name,
                title="최신 소식",
                url="https://example.com/new",
                description=query,
            )
        ]


class _FailingProvider:
    """검색 시 Provider 오류를 발생시키는 대역."""

    def __init__(self, name: str) -> None:
        self.name = name

    async def search(
        self, *, query: str, limit: int, language: str | None
    ) -> list[LatestArticle]:
        """항상 Provider 요청 실패를 발생시킨다."""
        raise LatestProviderError(self.name, "request_failed", "검색 실패")


def _patch_connection(
    monkeypatch: pytest.MonkeyPatch, connection: _FakeConnection
) -> None:
    """AsyncConnection.connect가 주어진 대역 연결을 반환하도록 교체한다."""

    class _FakeAsyncConnection:
        @classmethod
        async def connect(cls, *args: Any, **kwargs: Any) -> _FakeConnection:
            """대역 연결을 반환한다."""
            return connection

    monkeypatch.setattr(collector, "AsyncConnection", _FakeAsyncConnection)


def test_collection_batch_isolates_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """한 Provider가 실패해도 다른 Provider의 수집·저장이 완료되는지 검증한다."""
    connection = _FakeConnection(
        [
            [],  # set_system_job_scope
            [{"id": "source-1"}],  # INSERT global_sources
            [{"id": "run-1"}],  # INSERT global_collection_runs
            [{"id": "doc-1"}],  # INSERT global_source_documents → 새 캐시 문서
            [],  # UPDATE global_collection_runs
        ]
    )
    _patch_connection(monkeypatch, connection)
    monkeypatch.setattr(
        collector,
        "_build_provider",
        lambda name, **_: (
            _OneArticleProvider(name)
            if name == "naver"
            else _FailingProvider(name)
        ),
    )

    results = asyncio.run(
        collector.run_global_source_collection_batch(
            database_url="postgresql://fake",
            keywords=["AI", "Agent"],
            providers=["naver", "gdelt"],
        )
    )

    assert connection.closed is True
    naver_result = next(item for item in results if item["provider"] == "naver")
    gdelt_result = next(item for item in results if item["provider"] == "gdelt")
    assert naver_result["status"] == "completed"
    assert naver_result["created_count"] == 1
    assert gdelt_result["status"] == "failed"
    assert gdelt_result["error_code"] == "request_failed"


def test_collection_batch_supports_sns_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """YouTube·Reddit도 뉴스와 같은 경로로 수집·저장되는지 검증한다."""
    connection = _FakeConnection(
        [
            [],  # set_system_job_scope
            [{"id": "source-1"}],  # INSERT global_sources
            [{"id": "run-1"}],  # INSERT global_collection_runs
            [{"id": "doc-1"}],  # INSERT global_source_documents
            [],  # UPDATE global_collection_runs
        ]
    )
    _patch_connection(monkeypatch, connection)
    monkeypatch.setattr(
        collector, "_build_provider", lambda name, **_: _OneArticleProvider(name)
    )

    results = asyncio.run(
        collector.run_global_source_collection_batch(
            database_url="postgresql://fake",
            keywords=["후쿠오카"],
            providers=["youtube"],
        )
    )

    assert results[0]["provider"] == "youtube"
    assert results[0]["status"] == "completed"
    assert results[0]["created_count"] == 1


def test_collection_batch_requires_keywords(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """빈 키워드로 수집을 요청하면 ValueError를 발생시키는지 검증한다."""
    with pytest.raises(ValueError):
        asyncio.run(
            collector.run_global_source_collection_batch(
                database_url="postgresql://fake",
                keywords=["   "],
            )
        )


def test_build_provider_selects_and_validates() -> None:
    """Provider 이름별 구성과 자격 증명·미지원 오류를 검증한다."""
    gdelt = collector._build_provider(
        "gdelt",
        naver_client_id=None,
        naver_client_secret=None,
        gdelt_base_url=None,
    )
    assert isinstance(gdelt, GdeltNewsProvider)

    naver = collector._build_provider(
        "naver",
        naver_client_id="id",
        naver_client_secret="secret",
        gdelt_base_url=None,
    )
    assert isinstance(naver, NaverNewsProvider)

    google_news = collector._build_provider(
        "google_news",
        naver_client_id=None,
        naver_client_secret=None,
        gdelt_base_url=None,
    )
    assert isinstance(google_news, GoogleNewsRssProvider)

    newsapi = collector._build_provider(
        "newsapi",
        naver_client_id=None,
        naver_client_secret=None,
        gdelt_base_url=None,
        news_api_key="news-api-key",
    )
    assert isinstance(newsapi, NewsApiProvider)

    # SNS Provider는 자격 증명 없이 구성된다.
    youtube = collector._build_provider(
        "youtube",
        naver_client_id=None,
        naver_client_secret=None,
        gdelt_base_url=None,
    )
    assert isinstance(youtube, YouTubeSearchProvider)

    reddit = collector._build_provider(
        "reddit",
        naver_client_id=None,
        naver_client_secret=None,
        gdelt_base_url=None,
    )
    assert isinstance(reddit, RedditSearchProvider)

    with pytest.raises(LatestProviderError):
        collector._build_provider(
            "newsapi",
            naver_client_id=None,
            naver_client_secret=None,
            gdelt_base_url=None,
            news_api_key=None,
        )
    with pytest.raises(LatestProviderError):
        collector._build_provider(
            "naver",
            naver_client_id=None,
            naver_client_secret=None,
            gdelt_base_url=None,
        )
    with pytest.raises(LatestProviderError):
        collector._build_provider(
            "unknown",
            naver_client_id=None,
            naver_client_secret=None,
            gdelt_base_url=None,
        )


def test_build_provider_applies_sns_search_defaults() -> None:
    """SNS Provider는 "최근에 주목받은 글" 기본 검색 조건으로 구성된다.

    관련도순·최신순 기본값은 저조회수 개인 채널과 무관한 커뮤니티 글을 그대로
    담아 온다(2026-07-29 실측). 기본값이 사라지면 그 상태로 되돌아간다.
    """
    youtube = collector._build_provider(
        "youtube",
        naver_client_id=None,
        naver_client_secret=None,
        gdelt_base_url=None,
    )
    assert youtube._upload_window == "thisWeek"
    assert youtube._sort_by == "viewCount"

    reddit = collector._build_provider(
        "reddit",
        naver_client_id=None,
        naver_client_secret=None,
        gdelt_base_url=None,
    )
    assert reddit._sort == "top"
    assert reddit._time_filter == "week"


def test_build_provider_search_options_override_defaults() -> None:
    """Source별 search_options가 기본 검색 조건을 덮어쓴다.

    개념·튜토리얼 키워드를 모으는 Source는 최근 1주로 좁히면 안 되므로
    업로드 기간을 넓히거나 없앨 수 있어야 한다.
    """
    youtube = collector._build_provider(
        "youtube",
        naver_client_id=None,
        naver_client_secret=None,
        gdelt_base_url=None,
        search_options={"upload_window": "thisYear"},
    )
    assert youtube._upload_window == "thisYear"
    assert youtube._sort_by == "viewCount"          # 지정 안 한 값은 기본값 유지

    reddit = collector._build_provider(
        "reddit",
        naver_client_id=None,
        naver_client_secret=None,
        gdelt_base_url=None,
        search_options={"subreddits": ["MachineLearning"], "time_filter": "day"},
    )
    assert reddit._subreddits == ("MachineLearning",)
    assert reddit._time_filter == "day"


def test_build_provider_rejects_invalid_search_options() -> None:
    """잘못된 검색 설정은 Provider 실패로 감싸 다른 Provider 수집을 막지 않는다."""
    with pytest.raises(LatestProviderError):
        collector._build_provider(
            "youtube",
            naver_client_id=None,
            naver_client_secret=None,
            gdelt_base_url=None,
            search_options={"upload_window": "지난주"},
        )
    with pytest.raises(LatestProviderError):
        collector._build_provider(
            "reddit",
            naver_client_id=None,
            naver_client_secret=None,
            gdelt_base_url=None,
            search_options={"없는옵션": 1},
        )
