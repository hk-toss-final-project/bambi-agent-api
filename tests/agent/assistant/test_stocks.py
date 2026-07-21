"""주가 차트(stocks) 검증. 네트워크(Yahoo Finance)는 mock으로 대체한다."""

from agent.assistant.features import stocks

# 2026-07-13 ~ 07-15 (UTC) 일별 종가 3개. 중간에 거래 없는 날(None)을 섞는다.
_PAYLOAD = {
    "chart": {
        "result": [
            {
                "meta": {"symbol": "^KS11"},
                "timestamp": [1784044800, 1784131200, 1784217600, 1784304000],
                "indicators": {"quote": [{"close": [3010.50, None, 3055.20, 3110.00]}]},
            }
        ]
    }
}


def test_resolve_symbol_matches_known_keywords() -> None:
    """알려진 주가 키워드는 Yahoo 심볼·이름으로 해석된다."""
    assert stocks.resolve_symbol("코스피") == ("^KS11", "코스피")
    assert stocks.resolve_symbol("삼성전자 주가 전망") == ("005930.KS", "삼성전자")
    assert stocks.resolve_symbol("SK하이닉스") == ("000660.KS", "SK하이닉스")


def test_resolve_symbol_returns_none_for_non_stock() -> None:
    """주가 대상이 아닌 키워드는 None을 반환한다."""
    assert stocks.resolve_symbol("전고체 배터리") is None
    assert stocks.resolve_symbol("   ") is None


def test_parse_daily_closes_skips_null_and_limits_days() -> None:
    """close가 null인 날은 건너뛰고, 최근 days개만 남긴다."""
    series = stocks.parse_daily_closes(_PAYLOAD)
    assert [p["close"] for p in series] == [3010.50, 3055.20, 3110.00]
    assert all(isinstance(p["date"], str) and len(p["date"]) == 10 for p in series)

    assert [p["close"] for p in stocks.parse_daily_closes(_PAYLOAD, days=2)] == [3055.20, 3110.00]


def test_parse_daily_closes_handles_bad_payload() -> None:
    """예상과 다른 응답은 빈 리스트를 반환한다."""
    assert stocks.parse_daily_closes({}) == []
    assert stocks.parse_daily_closes({"chart": {"result": []}}) == []


def test_render_line_chart_svg_contains_polyline_and_change() -> None:
    """SVG에 폴리라인과 최종 변동률이 포함된다."""
    series = stocks.parse_daily_closes(_PAYLOAD)
    svg = stocks.render_line_chart_svg(series, "코스피")
    assert svg.startswith("<svg")
    assert "<polyline" in svg
    assert "%" in svg  # 변동률 표시


def test_build_stock_chart_returns_none_for_non_stock(monkeypatch) -> None:
    """주가 대상이 아니면 네트워크도 타지 않고 None."""
    called = {"fetch": False}
    monkeypatch.setattr(stocks, "_fetch_chart_json", lambda s: called.__setitem__("fetch", True) or {})
    assert stocks.build_stock_chart("커피") is None
    assert called["fetch"] is False


def test_build_stock_chart_builds_from_fetched_json(monkeypatch) -> None:
    """주가 키워드면 시세를 받아 차트 데이터를 만든다."""
    monkeypatch.setattr(stocks, "_fetch_chart_json", lambda symbol: _PAYLOAD)

    chart = stocks.build_stock_chart("코스피")

    assert chart is not None
    assert chart["symbol"] == "^KS11"
    assert chart["name"] == "코스피"
    assert chart["latest"] == 3110.00
    assert chart["chart_svg"].startswith("<svg")
    assert len(chart["series"]) == 3


def test_build_stock_chart_returns_none_on_fetch_error(monkeypatch) -> None:
    """네트워크 실패는 조용히 None(차트 없이 진행)."""

    def boom(symbol):
        raise RuntimeError("network down")

    monkeypatch.setattr(stocks, "_fetch_chart_json", boom)
    assert stocks.build_stock_chart("코스피") is None
