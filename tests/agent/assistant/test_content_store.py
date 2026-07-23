"""Global 본문 저장소 조회 경계(content_store) 검증.

실제 DB는 사용하지 않는다 — 비서는 DB 없이도 동작해야 하므로 폴백 경로가
계약의 핵심이다.
"""

from agent.assistant.features import content_store


def test_returns_empty_without_database_url(monkeypatch) -> None:
    """AGENT_DATABASE_URL이 없으면 조회 없이 빈 결과를 반환한다."""
    monkeypatch.delenv("AGENT_DATABASE_URL", raising=False)

    assert content_store.fetch_global_article_texts(["https://n.example/1"]) == {}


def test_returns_empty_for_empty_or_blank_urls(monkeypatch) -> None:
    """조회할 URL이 없으면 DB 연결 자체를 시도하지 않는다."""
    monkeypatch.setenv("AGENT_DATABASE_URL", "postgresql://unused")

    assert content_store.fetch_global_article_texts([]) == {}
    assert content_store.fetch_global_article_texts(["", ""]) == {}


def test_falls_back_to_empty_on_connection_failure(monkeypatch) -> None:
    """DB 연결 실패는 예외를 올리지 않고 빈 결과로 폴백한다(스니펫으로 계속)."""
    monkeypatch.setenv(
        "AGENT_DATABASE_URL", "postgresql://invalid-host.invalid:1/none"
    )
    import psycopg

    def boom(*args, **kwargs):
        raise psycopg.OperationalError("연결 실패")

    monkeypatch.setattr(psycopg, "connect", boom)

    assert content_store.fetch_global_article_texts(["https://n.example/1"]) == {}
