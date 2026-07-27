"""Report Builder 실시간 자료 어댑터(live_sources) 검증.

실제 네트워크·LLM은 호출하지 않는다. 키워드 비서 호출을 대체해 변환·병합 규칙만
결정적으로 검증한다.
"""

from agent.report_builder.features import live_sources
from shared.report_models import ReportContextDocument


def _doc(reference: str, score: float = 0.5) -> ReportContextDocument:
    """테스트용 근거 문서를 만든다."""
    return ReportContextDocument(
        reference=reference,
        document_version_id="v1",
        chunk_id=reference,
        namespace_key="personal",
        title=f"제목 {reference}",
        content="본문",
        url=None,
        score=score,
    )


def test_collect_live_context_converts_items(monkeypatch) -> None:
    """비서 선별 아이템을 Report Builder 근거 문서로 변환한다."""
    monkeypatch.setattr(
        live_sources,
        "assist_daily_agent",
        lambda topic, user_id, model="gpt-4.1-mini", **kwargs: {
            "mode": "daily",
            "attempts": ["코스피"],
            "items": [
                {
                    "title": "코스피 급락",
                    "summary": "지수가 4% 내렸다.",
                    "score": 0.42,
                    "sources": [
                        {"source_type": "news", "title": "기사A", "url": "https://a.test/1"},
                        {"source_type": "news", "title": "기사B", "url": "https://b.test/2"},
                    ],
                }
            ],
        },
    )

    documents = live_sources.collect_live_context("코스피", "minji")

    assert len(documents) == 1
    document = documents[0]
    # 참조는 프롬프트 인용 체계(P/G/L)에 맞는 L{n} 형식이어야 한다.
    assert document.reference == "L1"
    assert document.title == "코스피 급락"
    assert document.score == 0.42
    assert document.url == "https://a.test/1"      # 대표 출처 URL
    assert "지수가 4% 내렸다." in document.content
    assert "https://b.test/2" in document.content  # 나머지 출처도 본문에 남는다
    assert document.namespace_key == "live-source"


def test_collect_live_context_does_not_pollute_history_or_write_report(monkeypatch) -> None:
    """리포트 근거 수집은 이력을 기록하지 않고 브리핑도 생성하지 않는다.

    이 호출이 이력을 남기면 사용자의 일간 브리핑에서 같은 소식이 최대 7일간
    가려지고(이력 오염), 버릴 브리핑 Markdown을 만들면 LLM 비용만 든다.
    """
    captured: dict = {}

    def fake_agent(topic, user_id, model="gpt-4.1-mini", **kwargs):
        captured.update(kwargs)
        return {"items": []}

    monkeypatch.setattr(live_sources, "assist_daily_agent", fake_agent)

    live_sources.collect_live_context("코스피", "minji")

    assert captured["record_history"] is False
    assert captured["include_report"] is False


def test_collect_live_context_survives_failure(monkeypatch) -> None:
    """실시간 수집이 실패해도 예외를 올리지 않고 빈 목록을 준다.

    실시간 자료가 없다고 해서 개인 Wiki 기반 생성까지 막을 이유는 없다.
    """

    def boom(topic, user_id, model="gpt-4.1-mini"):
        raise RuntimeError("네트워크 오류")

    monkeypatch.setattr(live_sources, "assist_daily_agent", boom)

    assert live_sources.collect_live_context("코스피", "minji") == []


def test_collect_live_context_skips_empty_items(monkeypatch) -> None:
    """제목과 요약이 모두 빈 아이템은 근거로 쓰지 않는다."""
    monkeypatch.setattr(
        live_sources,
        "assist_daily_agent",
        lambda topic, user_id, model="gpt-4.1-mini", **kwargs: {
            "items": [{"title": "", "summary": "", "sources": []}, "문자열아이템"]
        },
    )

    assert live_sources.collect_live_context("코스피", "minji") == []


def test_collect_live_context_skips_items_without_source_url(monkeypatch) -> None:
    """출처 URL이 없는 아이템은 건너뛰고 순번을 이어 붙인다.

    실시간 자료는 Wiki Version이 없어 Citation 저장 시 URL이 유일한 출처 증빙이다.
    """
    monkeypatch.setattr(
        live_sources,
        "assist_daily_agent",
        lambda topic, user_id, model="gpt-4.1-mini", **kwargs: {
            "items": [
                {"title": "출처 없는 개념 정리", "summary": "요약", "sources": []},
                {
                    "title": "출처 있는 소식",
                    "summary": "요약",
                    "sources": [{"source_type": "news", "title": "기사", "url": "https://a.test/1"}],
                },
            ]
        },
    )

    documents = live_sources.collect_live_context("코스피", "minji")

    assert [d.reference for d in documents] == ["L1"]  # 건너뛴 아이템은 번호를 차지하지 않는다
    assert documents[0].title == "출처 있는 소식"


def test_select_generation_context_puts_personal_first() -> None:
    """개인 Wiki 문서를 앞에 두고 실시간 자료를 점수 순으로 붙인다."""
    personal = [_doc("p1"), _doc("p2")]
    live = [_doc("l-low", score=0.1), _doc("l-high", score=0.9)]

    selected = live_sources.select_generation_context(personal, live)

    assert [d.reference for d in selected] == ["p1", "p2", "l-high", "l-low"]


def test_select_generation_context_applies_limit_and_dedup() -> None:
    """중복 참조를 제거하고 상한을 적용한다."""
    personal = [_doc("a"), _doc("b")]
    live = [_doc("b", score=0.9), _doc("c", score=0.8)]

    selected = live_sources.select_generation_context(personal, live, max_documents=3)

    assert [d.reference for d in selected] == ["a", "b", "c"]  # b 중복 제거


def test_select_generation_context_tolerates_plain_values() -> None:
    """참조 ID가 없는 형태도 그대로 통과시키되 중복만 거른다."""
    assert live_sources.select_generation_context(["x", "x"], ["y"]) == ["x", "y"]
