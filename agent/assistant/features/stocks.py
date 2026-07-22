"""주가/지수 차트 생성.

키워드가 주식·지수를 가리키면 일별 종가 시계열을 받아와 간단한 SVG 라인 차트를
만든다. 데이터는 무료·API 키 불필요한 Yahoo Finance chart API를 쓴다.

네트워크 경계(_fetch_chart_json)를 분리해 테스트에서 대체할 수 있게 하고, 심볼 해석과
SVG 렌더링은 순수 함수로 두어 오프라인에서 검증 가능하게 한다. 데이터를 못 받거나
키워드가 주가 대상이 아니면 None을 반환한다(차트 없음).

심볼은 Yahoo 표기를 따른다(코스피 ^KS11, 코스닥 ^KQ11, 국내 종목 <코드>.KS).
매칭되지 않는 키워드는 차트를 만들지 않는다.
"""

from __future__ import annotations

# 키워드(정규화: 소문자·공백 제거) → (Yahoo 심볼, 표시 이름).
# 한 키워드가 여러 표기를 가지므로 별칭을 여러 개 둔다. 필요 시 확장한다.
_SYMBOL_MAP: dict[str, tuple[str, str]] = {
    "코스피": ("^KS11", "코스피"),
    "kospi": ("^KS11", "코스피"),
    "코스닥": ("^KQ11", "코스닥"),
    "kosdaq": ("^KQ11", "코스닥"),
    "삼성전자": ("005930.KS", "삼성전자"),
    "sk하이닉스": ("000660.KS", "SK하이닉스"),
    "하이닉스": ("000660.KS", "SK하이닉스"),
    "네이버": ("035420.KS", "NAVER"),
    "카카오": ("035720.KS", "카카오"),
    "현대차": ("005380.KS", "현대차"),
    "lg에너지솔루션": ("373220.KS", "LG에너지솔루션"),
    "lg엔솔": ("373220.KS", "LG에너지솔루션"),
    "나스닥": ("^IXIC", "나스닥"),
    "nasdaq": ("^IXIC", "나스닥"),
    "s&p500": ("^GSPC", "S&P 500"),
    "sp500": ("^GSPC", "S&P 500"),
    "다우": ("^DJI", "다우존스"),
    "애플": ("AAPL", "Apple"),
    "apple": ("AAPL", "Apple"),
    "테슬라": ("TSLA", "Tesla"),
    "tesla": ("TSLA", "Tesla"),
    "엔비디아": ("NVDA", "NVIDIA"),
    "nvidia": ("NVDA", "NVIDIA"),
}

_FETCH_TIMEOUT = 15.0
_DEFAULT_DAYS = 30


def resolve_symbol(keyword: str) -> tuple[str, str] | None:
    """키워드에서 주가 심볼과 표시 이름을 찾는다. 대상이 아니면 None.

    정규화한 키워드에 별칭이 포함되면 매칭한다(긴 별칭 우선).
    """
    normalized = keyword.strip().lower().replace(" ", "")
    if not normalized:
        return None
    for alias in sorted(_SYMBOL_MAP, key=len, reverse=True):
        if alias in normalized:
            return _SYMBOL_MAP[alias]
    return None


def _fetch_chart_json(symbol: str, range_: str = "1mo") -> dict:
    """Yahoo Finance chart API에서 일별 시세 JSON을 받아온다(네트워크 경계).

    실패 시 예외를 던진다. 브라우저형 User-Agent가 없으면 차단될 수 있어 명시한다.
    """
    import httpx
    from urllib.parse import quote

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
    response = httpx.get(
        url,
        params={"range": range_, "interval": "1d"},
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; report-builder-keyword-assistant/0.1)"
        },
        timeout=_FETCH_TIMEOUT,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response.json()


def parse_daily_closes(payload: dict, days: int = _DEFAULT_DAYS) -> list[dict[str, object]]:
    """Yahoo chart JSON을 파싱해 최근 days개의 {date, close}를 반환한다.

    거래가 없는 날(close=null)은 건너뛴다.
    """
    from datetime import UTC, datetime

    try:
        result = payload["chart"]["result"][0]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        return []

    series: list[dict[str, object]] = []
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        date = datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")
        series.append({"date": date, "close": float(close)})
    return series[-days:]


def render_line_chart_svg(series: list[dict[str, object]], label: str, width: int = 596, height: int = 200) -> str:
    """종가 시계열을 간단한 SVG 라인 차트로 그린다(순수 함수).

    디자인 토큰(var(--signal) 등)을 사용해 페이지 테마에 맞춘다.
    """
    closes = [float(p["close"]) for p in series]
    if len(closes) < 2:
        return ""

    pad_x, pad_top, pad_bottom = 12, 20, 24
    lo, hi = min(closes), max(closes)
    span = (hi - lo) or 1.0
    plot_w = width - pad_x * 2
    plot_h = height - pad_top - pad_bottom

    points = []
    for i, value in enumerate(closes):
        x = pad_x + plot_w * i / (len(closes) - 1)
        y = pad_top + plot_h * (1 - (value - lo) / span)
        points.append(f"{x:.1f},{y:.1f}")
    polyline = " ".join(points)

    last = closes[-1]
    first = closes[0]
    change_pct = (last - first) / first * 100 if first else 0.0
    change_color = "var(--ok)" if change_pct >= 0 else "var(--err)"
    sign = "+" if change_pct >= 0 else ""

    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'preserveAspectRatio="xMidYMid meet" style="width:100%;height:auto;">'
        f'<rect width="{width}" height="{height}" style="fill:var(--bg-soft)" rx="10"/>'
        f'<polyline points="{polyline}" fill="none" style="stroke:var(--signal)" stroke-width="2.5" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f'<text x="{pad_x}" y="16" style="fill:var(--ink-dim)" font-size="13">{label} · 최근 {len(closes)}일</text>'
        f'<text x="{width - pad_x}" y="{height - 8}" text-anchor="end" '
        f'style="fill:{change_color}" font-size="14" font-weight="700">{last:,.2f} ({sign}{change_pct:.2f}%)</text>'
        f'</svg>'
    )


def build_stock_chart(keyword: str, days: int = _DEFAULT_DAYS) -> dict[str, object] | None:
    """키워드가 주가 대상이면 시계열을 받아 차트 데이터를 만든다. 아니면 None.

    반환: {symbol, name, series, chart_svg, latest, change_pct}
    네트워크·파싱 실패는 조용히 None으로 처리한다(차트 없이 진행).
    """
    resolved = resolve_symbol(keyword)
    if resolved is None:
        return None
    symbol, name = resolved

    try:
        payload = _fetch_chart_json(symbol)
    except Exception:
        return None

    series = parse_daily_closes(payload, days=days)
    if len(series) < 2:
        return None

    closes = [float(p["close"]) for p in series]
    latest = closes[-1]
    change_pct = (latest - closes[0]) / closes[0] * 100 if closes[0] else 0.0

    return {
        "symbol": symbol,
        "name": name,
        "series": series,
        "chart_svg": render_line_chart_svg(series, name),
        "latest": latest,
        "change_pct": round(change_pct, 2),
    }
