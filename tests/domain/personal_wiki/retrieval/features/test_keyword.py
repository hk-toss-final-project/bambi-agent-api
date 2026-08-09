"""개인 Wiki·Global Keyword Search 기능 경계를 검증한다."""

import asyncio

from domain.personal_wiki.retrieval.features import keyword


def test_prag_001_delegates_scope_query_and_limit(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """검증한 사용자·검색어·Scope별 상한을 Keyword 저장소에 전달한다."""
    captured: dict[str, object] = {}

    async def fake_load(*args, **kwargs):  # type: ignore[no-untyped-def]
        """Keyword 저장소 호출 인자를 기록한다."""
        captured.update(kwargs)
        return []

    monkeypatch.setattr(keyword, "load_report_context", fake_load)

    result = asyncio.run(
        keyword.prag_001(
            object(),  # type: ignore[arg-type]
            user_id="user-1",
            query="폭염",
            top_k_per_scope=7,
        )
    )

    assert result == []
    assert captured == {
        "user_id": "user-1",
        "query": "폭염",
        "top_k_per_scope": 7,
    }
