"""Global 본문 저장소 조회 경계(content_store) 검증.

실제 DB는 사용하지 않는다 — 비서는 DB 없이도 동작해야 하므로 폴백 경로가
계약의 핵심이다.
"""

from agent.assistant.features import content_store


def test_returns_empty_without_database_url(monkeypatch) -> None:
    """AGENT_DATABASE_URL이 없으면 조회 없이 빈 결과를 반환한다."""
    monkeypatch.delenv("AGENT_DATABASE_URL", raising=False)

    assert content_store.fetch_global_article_assets(["https://n.example/1"]) == {}


def test_returns_empty_for_empty_or_blank_urls(monkeypatch) -> None:
    """조회할 URL이 없으면 DB 연결 자체를 시도하지 않는다."""
    monkeypatch.setenv("AGENT_DATABASE_URL", "postgresql://unused")

    assert content_store.fetch_global_article_assets([]) == {}
    assert content_store.fetch_global_article_assets(["", ""]) == {}


def test_falls_back_to_empty_on_connection_failure(monkeypatch) -> None:
    """DB 연결 실패는 예외를 올리지 않고 빈 결과로 폴백한다(스니펫으로 계속)."""
    monkeypatch.setenv(
        "AGENT_DATABASE_URL", "postgresql://invalid-host.invalid:1/none"
    )
    import psycopg

    def boom(*args, **kwargs):
        raise psycopg.OperationalError("연결 실패")

    monkeypatch.setattr(psycopg, "connect", boom)

    assert content_store.fetch_global_article_assets(["https://n.example/1"]) == {}


def test_returns_cached_markdown_and_image_url(monkeypatch) -> None:
    """캐시 본문과 대표 이미지 URL을 같은 기사 자산으로 반환한다."""
    monkeypatch.setenv("AGENT_DATABASE_URL", "postgresql://cache")
    import psycopg

    class FakeCursor:
        """성공 조회 결과를 제공하는 테스트 Cursor다."""

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def execute(self, query, params) -> None:
            assert "image_url" in query
            assert params == (["https://n.example/1"],)

        def fetchall(self):
            return [
                (
                    "https://n.example/1",
                    "저장된 본문 제목입니다",
                    "# 저장된 본문",
                    "https://cdn.example/cover.jpg",
                )
            ]

    class FakeConnection:
        """Cursor Context를 제공하는 테스트 Connection이다."""

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(psycopg, "connect", lambda dsn: FakeConnection())

    assert content_store.fetch_global_article_assets(["https://n.example/1"]) == {
        "https://n.example/1": {
            "markdown": "# 저장된 본문",
            "image_url": "https://cdn.example/cover.jpg",
        }
    }


def test_replaces_cached_banner_with_image_from_stored_markdown(monkeypatch) -> None:
    """DB에 잘못 저장된 배너 URL도 저장된 기사 본문 이미지로 교체한다."""
    monkeypatch.setenv("AGENT_DATABASE_URL", "postgresql://cache")
    import psycopg

    class FakeCursor:
        """배너 캐시와 본문 이미지가 함께 있는 조회 결과를 제공한다."""

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def execute(self, query, params) -> None:
            assert "title" in query

        def fetchall(self):
            return [
                (
                    "https://n.example/1",
                    "본문 대표 이미지를 다시 찾는 긴 기사 제목",
                    "# 본문 대표 이미지를 다시 찾는 긴 기사 제목\n"
                    "![사진](https://cdn.example/article/hero.jpg)\n본문",
                    "https://menu.example/news/banner/ad.jpg",
                )
            ]

    class FakeConnection:
        """테스트 Cursor Context를 제공한다."""

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(psycopg, "connect", lambda dsn: FakeConnection())

    assets = content_store.fetch_global_article_assets(["https://n.example/1"])

    assert assets["https://n.example/1"]["image_url"] == (
        "https://cdn.example/article/hero.jpg"
    )
