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


def _capture_assistant_call(monkeypatch) -> dict[str, object]:
    """비서 호출 인자를 가로채고 빈 결과를 돌려준다."""
    captured: dict[str, object] = {}

    def fake_assist(topic, user_id, model="gpt-4.1-mini", **kwargs):
        captured["topic"] = topic
        captured["extra_queries"] = list(kwargs.get("extra_queries") or [])
        return {"mode": "daily", "items": []}

    monkeypatch.setattr(live_sources, "assist_daily_agent", fake_assist)
    return captured


def test_wiki_이웃_키워드를_보조_검색어로_함께_던진다(monkeypatch) -> None:
    """리포트 수집은 관심 키워드 하나가 아니라 연결된 이웃도 함께 검색한다."""
    captured = _capture_assistant_call(monkeypatch)

    live_sources.collect_live_context(
        "코스피", "minji", related_keywords=["코스닥시장", "지수선물"]
    )

    # 원 토픽은 비서가 keyword로 따로 받으므로 보조 검색어에는 들어가지 않는다.
    assert captured["topic"] == "코스피"
    assert captured["extra_queries"] == ["코스닥시장", "지수선물"]


def test_이웃이_없으면_기존과_같이_검색어_하나로_수집한다(monkeypatch) -> None:
    """고립 토픽에서 회귀가 없어야 한다."""
    captured = _capture_assistant_call(monkeypatch)

    live_sources.collect_live_context("코스피", "minji")

    assert captured["extra_queries"] == []


def test_확장_상한은_환경변수로_끌_수_있다(monkeypatch) -> None:
    """A/B 비교를 위해 0으로 두면 이전 동작(검색어 1개)으로 되돌아간다."""
    monkeypatch.setenv("REPORT_QUERY_EXPANSION_LIMIT", "0")
    captured = _capture_assistant_call(monkeypatch)

    live_sources.collect_live_context("코스피", "minji", related_keywords=["코스닥시장"])

    assert captured["extra_queries"] == []


def test_보조_검색어_총량은_상한을_넘지_않는다(monkeypatch) -> None:
    """수집 시간이 검색어 수에 비례하므로 총량을 통제한다."""
    monkeypatch.setenv("REPORT_QUERY_EXPANSION_LIMIT", "2")
    captured = _capture_assistant_call(monkeypatch)

    live_sources.collect_live_context(
        "코스피", "minji", related_keywords=["이웃1", "이웃2", "이웃3", "이웃4"]
    )

    assert captured["extra_queries"] == ["이웃1", "이웃2"]


def test_이웃_조회_상한은_확장_상한보다_여유를_둔다(monkeypatch) -> None:
    """원 토픽과 겹치는 이웃이 걸러질 것을 감안해 상한보다 많이 가져온다."""
    monkeypatch.setenv("REPORT_QUERY_EXPANSION_LIMIT", "2")

    assert live_sources.related_keyword_fetch_limit() == 5


def test_확장이_꺼져_있으면_이웃을_조회하지_않는다(monkeypatch) -> None:
    """확장 OFF면 호출자가 DB 조회 자체를 건너뛸 수 있어야 한다."""
    monkeypatch.setenv("REPORT_QUERY_EXPANSION_LIMIT", "0")

    assert live_sources.related_keyword_fetch_limit() == 0


def test_기본_확장_상한은_이웃_셋이다(monkeypatch) -> None:
    """온디맨드가 "고른 주제 하나 + Wiki 연결 상위 태그 3개"를 엮는 경로다.

    2026-08-10 계약으로 온디맨드가 단일 주제 + Wiki 이웃 확장으로 확정됐다.
    기본값이 도로 2로 내려가면 태그가 하나 모자란 리포트가 조용히 나간다.
    """
    monkeypatch.delenv("REPORT_QUERY_EXPANSION_LIMIT", raising=False)
    captured = _capture_assistant_call(monkeypatch)

    live_sources.collect_live_context(
        "코스피", "minji", related_keywords=["이웃1", "이웃2", "이웃3", "이웃4"]
    )

    assert captured["extra_queries"] == ["이웃1", "이웃2", "이웃3"]
