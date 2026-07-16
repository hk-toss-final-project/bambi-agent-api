"""주가 차트(stocks) 검증. 네트워크(Stooq)는 mock으로 대체한다."""

from agent.assistant import stocks

_CSV = (
    "Date,Open,High,Low,Close,Volume\n"
    "2026-07-11,3000,3050,2990,3010.50,1000\n"
    "2026-07-12,3010,3080,3005,3055.20,1200\n"
    "2026-07-14,3055,3120,3050,3110.00,1500\n"
)


def test_resolve_symbol_matches_known_keywords() -> None:
    """알려진 주가 키워드는 심볼·이름으로 해석된다."""
    assert stocks.resolve_symbol("코스피") == ("^KOSPI", "코스피")
    assert stocks.resolve_symbol("삼성전자 주가 전망") == ("005930.KR", "삼성전자")
    assert stocks.resolve_symbol("SK하이닉스") == ("000660.KR", "SK하이닉스")


def test_resolve_symbol_returns_none_for_non_stock() -> None:
    """주가 대상이 아닌 키워드는 None을 반환한다."""
    assert stocks.resolve_symbol("전고체 배터리") is None
    assert stocks.resolve_symbol("   ") is None


def test_parse_daily_closes_reads_recent_closes() -> None:
    """CSV에서 최근 종가 시계열을 파싱한다."""
    series = stocks.parse_daily_closes(_CSV, days=2)
    assert series == [
        {"date": "2026-07-12", "close": 3055.20},
        {"date": "2026-07-14", "close": 3110.00},
    ]


def test_parse_daily_closes_handles_empty() -> None:
    """헤더만 있거나 빈 CSV는 빈 리스트를 반환한다."""
    assert stocks.parse_daily_closes("Date,Close\n") == []
    assert stocks.parse_daily_closes("") == []


def test_render_line_chart_svg_contains_polyline_and_change() -> None:
    """SVG에 폴리라인과 최종 변동률이 포함된다."""
    series = stocks.parse_daily_closes(_CSV)
    svg = stocks.render_line_chart_svg(series, "코스피")
    assert svg.startswith("<svg")
    assert "<polyline" in svg
    assert "3,110" in svg or "3110" in svg  # 최종 종가 표시
    assert "%" in svg  # 변동률 표시


def test_build_stock_chart_returns_none_for_non_stock(monkeypatch) -> None:
    """주가 대상이 아니면 네트워크도 타지 않고 None."""
    called = {"fetch": False}
    monkeypatch.setattr(stocks, "_fetch_stooq_csv", lambda s: called.__setitem__("fetch", True) or "")
    assert stocks.build_stock_chart("커피") is None
    assert called["fetch"] is False


def test_build_stock_chart_builds_from_fetched_csv(monkeypatch) -> None:
    """주가 키워드면 CSV를 받아 차트 데이터를 만든다."""
    monkeypatch.setattr(stocks, "_fetch_stooq_csv", lambda symbol: _CSV)

    chart = stocks.build_stock_chart("코스피")

    assert chart is not None
    assert chart["symbol"] == "^KOSPI"
    assert chart["name"] == "코스피"
    assert chart["latest"] == 3110.00
    assert chart["chart_svg"].startswith("<svg")
    assert len(chart["series"]) == 3


def test_build_stock_chart_returns_none_on_fetch_error(monkeypatch) -> None:
    """네트워크 실패는 조용히 None(차트 없이 진행)."""
    def boom(symbol):
        raise RuntimeError("network down")

    monkeypatch.setattr(stocks, "_fetch_stooq_csv", boom)
    assert stocks.build_stock_chart("코스피") is None
