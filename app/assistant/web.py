"""키워드 비서 웹 라우터.

/ 에서 사용자 식별자와 키워드를 입력받아 YouTube 자막 요약, Reddit 게시글 요약,
최근·중복 제거 기사 URL을 함께 보여준다. YouTube는 최근(48시간 이내) 영상 중
사용자가 아직 보지 않은 영상만 남긴다. "봤다"는 판단은 실제로 영상 링크를
클릭했을 때만 기록한다(/watch 리다이렉트 경유). 기사는 최근(48시간 이내) 발행된
기사 중 이전 리포트에서 이미 보여준 적 없는 것만 남긴다.

실제 외부 호출(YouTube, Reddit, Google News RSS, Jina Reader)과 LLM 요약이
일어나므로 응답에 다소 시간이 걸린다.
"""

from __future__ import annotations

import html
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Form
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse

from pathlib import Path

from agent.assistant import history
from agent.assistant.report import build_report_context, collect_sources, generate_report
from agent.assistant.service import assist
from agent.assistant.stocks import build_stock_chart

# report-detail 디자인 핸드오프에서 가져온 공유 CSS(tokens·base·product-components).
# 보고서 결과 페이지를 AlphaCatcher 디자인으로 렌더링하는 데 사용한다.
_DESIGN_DIR = Path(__file__).resolve().parent / "design"


def _load_design_css() -> str:
    """vendoring한 디자인 CSS 세 파일을 하나로 합쳐 인라인용 문자열로 반환한다."""
    parts = []
    for name in ("tokens.css", "base.css", "product-components.css"):
        path = _DESIGN_DIR / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


_DESIGN_CSS = _load_design_css()

assistant_router = APIRouter(tags=["assistant"])

_PAGE_STYLE = """
<style>
  body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; max-width: 860px;
         margin: 2rem auto; padding: 0 1rem; color: #1c1c1e; line-height: 1.6; }
  h1 { font-size: 1.5rem; } h2 { font-size: 1.15rem; margin-top: 2rem; }
  label { display: block; font-size: .85rem; color: #6a6a72; margin: .8rem 0 .3rem; }
  input { width: 100%; padding: .7rem; font-size: 1rem; box-sizing: border-box;
          border: 1px solid #ccc; border-radius: 8px; }
  button { margin-top: 1rem; padding: .7rem 1.5rem; font-size: 1rem; border: 0;
           border-radius: 8px; background: #d6402c; color: #fff; cursor: pointer; }
  .card { border: 1px solid #e3e3e8; border-radius: 12px; padding: 1rem 1.2rem; margin: .9rem 0;
          background: #fafafd; }
  .card a { color: #1a56c4; text-decoration: none; font-weight: 500; }
  .meta { color: #8a8a92; font-size: .85rem; margin: .15rem 0 .5rem; }
  .summary { white-space: pre-wrap; }
  .note { color: #a15; font-size: .9rem; }
  .banner { background:#eef4ff; border:1px solid #cfe0ff; border-radius:8px; padding:.6rem .9rem;
            font-size:.9rem; color:#234; }
  .err { background:#fff1f0; border:1px solid #ffccc7; border-radius:8px; padding:.5rem .8rem;
         font-size:.85rem; color:#a8071a; margin:.4rem 0; }
</style>
"""


def _form_html(user_id: str = "") -> str:
    """사용자 식별자를 미리 채운 키워드 입력 폼을 만든다."""
    user_id_value = html.escape(user_id)
    return f"""
<!doctype html>
<meta charset="utf-8">
<title>키워드 비서 AI</title>
{_PAGE_STYLE}
<h1>🔎 키워드 비서 AI</h1>
<p class="banner">키워드를 입력하면 관련 YouTube 영상 자막과 Reddit 게시글을 요약하고,
최근 뉴스 URL을 중복 없이 모아줍니다. YouTube와 기사 모두 이전에 보여준 것은
기억해뒀다가 다음에는 새 것 위주로 보여줍니다.</p>
<form method="post" action="/search">
  <label for="user_id">이름 / 아이디</label>
  <input id="user_id" name="user_id" required placeholder="예: minji" value="{user_id_value}">
  <label for="keyword">키워드</label>
  <input id="keyword" name="keyword" required placeholder="예: 전고체 배터리" autofocus>
  <button type="submit">검색</button>
</form>
"""


@assistant_router.get("/", response_class=HTMLResponse)
async def assistant_form(user_id: str = "") -> str:
    """키워드 입력 폼 페이지를 반환한다. user_id가 주어지면 미리 채운다."""
    return _form_html(user_id)


def _watch_link(user_id: str, keyword: str, video: dict[str, object]) -> str:
    """클릭을 기록한 뒤 실제 영상으로 리다이렉트하는 /watch 링크를 만든다."""
    params = urlencode(
        {
            "user_id": user_id,
            "keyword": keyword,
            "video_id": str(video.get("video_id") or ""),
            "url": str(video.get("url") or ""),
            "title": str(video.get("title") or ""),
        },
        quote_via=quote,
    )
    return f"/watch?{params}"


def _render_youtube(items: list[dict[str, object]], user_id: str, keyword: str) -> str:
    """YouTube 요약 카드를 HTML로 렌더링한다. 링크는 시청 기록용 리다이렉트를 거친다."""
    if not items:
        return "<p class='note'>관련 영상을 찾지 못했습니다.</p>"
    cards = []
    for item in items:
        title = html.escape(str(item.get("title") or ""))
        link = html.escape(_watch_link(user_id, keyword, item))
        channel = html.escape(str(item.get("channel") or ""))
        duration = html.escape(str(item.get("duration") or ""))
        published = html.escape(str(item.get("published_time") or ""))
        meta = " · ".join(part for part in [channel, duration, published] if part)
        if item.get("summary"):
            body = f"<div class='summary'>{html.escape(str(item['summary']))}</div>"
        else:
            body = f"<div class='note'>{html.escape(str(item.get('note') or '요약 없음'))}</div>"
        cards.append(
            f"<div class='card'><a href='{link}' target='_blank'>{title}</a>"
            f"<div class='meta'>{meta}</div>{body}</div>"
        )
    return "\n".join(cards)


def _render_reddit(items: list[dict[str, object]]) -> str:
    """최근 작성된 Reddit 게시글 요약 카드를 HTML로 렌더링한다."""
    if not items:
        return "<p class='note'>최근 작성된 게시글이 없습니다.</p>"
    cards = []
    for item in items:
        title = html.escape(str(item.get("title") or ""))
        url = html.escape(str(item.get("url") or ""))
        subreddit = html.escape(str(item.get("subreddit") or ""))
        published = html.escape(str(item.get("published") or ""))
        meta = " · ".join(part for part in [f"r/{subreddit}" if subreddit else "", published] if part)
        if item.get("summary"):
            body = f"<div class='summary'>{html.escape(str(item['summary']))}</div>"
        else:
            body = f"<div class='note'>{html.escape(str(item.get('note') or '요약 없음'))}</div>"
        cards.append(
            f"<div class='card'><a href='{url}' target='_blank'>{title}</a>"
            f"<div class='meta'>{meta}</div>{body}</div>"
        )
    return "\n".join(cards)


def _render_articles(items: list[dict[str, object]]) -> str:
    """최근 발행된 새 기사 카드를 링크와 요약만으로 렌더링한다."""
    if not items:
        return "<p class='note'>새로운 기사가 없습니다.</p>"
    cards = []
    for item in items:
        title = html.escape(str(item.get("title") or ""))
        url = html.escape(str(item.get("url") or ""))
        snippet = html.escape(str(item.get("snippet") or ""))
        cards.append(
            f"<div class='card'><a href='{url}' target='_blank'>{title}</a>"
            f"<div class='summary'>{snippet}</div></div>"
        )
    return "\n".join(cards)


@assistant_router.post("/search", response_class=HTMLResponse)
async def assistant_search(user_id: str = Form(...), keyword: str = Form(...)) -> str:
    """키워드로 비서를 실행하고 결과 페이지를 반환한다."""
    result = await run_in_threadpool(assist, keyword, user_id=user_id)

    errors_html = "".join(
        f"<div class='err'>{html.escape(str(err))}</div>" for err in result.get("errors", [])
    )
    back_link = f"/?{urlencode({'user_id': result['user_id']}, quote_via=quote)}"

    return f"""
<!doctype html>
<meta charset="utf-8">
<title>{html.escape(result['keyword'])} — 키워드 비서</title>
{_PAGE_STYLE}
<h1>🔎 “{html.escape(result['keyword'])}” 결과</h1>
<p><a href="{back_link}">← 다른 키워드로 검색</a></p>
{errors_html}
<h2>▶️ 관련 YouTube 요약</h2>
{_render_youtube(result.get("youtube", []), result["user_id"], result["keyword"])}
<h2>👽 최근 Reddit 게시글 요약</h2>
{_render_reddit(result.get("reddit", []))}
<h2>📰 최근 기사 (새 소식만)</h2>
{_render_articles(result.get("articles", []))}
"""


@assistant_router.get("/watch")
async def watch_redirect(user_id: str, keyword: str, video_id: str, url: str, title: str = "") -> RedirectResponse:
    """영상 클릭을 시청 이력으로 기록한 뒤 실제 YouTube 페이지로 리다이렉트한다."""
    await run_in_threadpool(history.record_watch, user_id, keyword, video_id, title, url)
    return RedirectResponse(url, status_code=302)


_REPORT_FORM_HTML = f"""
<!doctype html>
<meta charset="utf-8">
<title>개인화 보고서</title>
{_PAGE_STYLE}
<h1>📄 개인화 보고서 생성</h1>
<p class="banner">키워드로 YouTube·뉴스·Reddit 최신 자료를 모아 하나의 보고서로 요약합니다.
사용자 설정(언어·플랜)과 개인 Wiki 지식은 연동되면 자동 반영됩니다.</p>
<form method="post" action="/report/generate">
  <label for="user_id">이름 / 아이디</label>
  <input id="user_id" name="user_id" required placeholder="예: minji">
  <label for="keyword">키워드</label>
  <input id="keyword" name="keyword" required placeholder="예: 전고체 배터리" autofocus>
  <button type="submit">보고서 생성</button>
</form>
"""


def _render_markdown(text: str) -> str:
    """보고서 Markdown을 가벼운 규칙으로 HTML로 변환한다(제목·불릿·굵게).

    외부 라이브러리 없이 최소한만 처리하고, 그 외는 그대로 표시한다.
    """
    import re

    lines = text.splitlines()
    out: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in lines:
        line = html.escape(raw.rstrip())
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        # [텍스트](URL) 마크다운 링크를 클릭 가능한 <a>로 변환한다.
        line = re.sub(
            r"\[([^\]]+)\]\((https?://[^)]+)\)",
            r'<a href="\2" target="_blank">\1</a>',
            line,
        )
        if line.startswith("### "):
            close_list()
            out.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("## "):
            close_list()
            out.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            close_list()
            out.append(f"<h1>{line[2:]}</h1>")
        elif re.match(r"^[-*] ", line):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{line[2:]}</li>")
        elif line.strip() == "":
            close_list()
        else:
            close_list()
            out.append(f"<p>{line}</p>")
    close_list()
    return "\n".join(out)


@assistant_router.get("/report", response_class=HTMLResponse)
async def report_form() -> str:
    """보고서 생성 입력 폼 페이지를 반환한다."""
    return _REPORT_FORM_HTML


def _run_report(keyword: str, user_id: str) -> dict[str, object]:
    """최신 자료를 수집하고 개인화 보고서 본문과 출처 목록을 만든다(블로킹 작업 묶음)."""
    assist_result = assist(keyword, user_id=user_id)
    fresh = {
        "youtube": assist_result.get("youtube", []),
        "articles": assist_result.get("articles", []),
        "reddit": assist_result.get("reddit", []),
    }
    # TODO: ①user_context_snapshots(DB), ②개인 Wiki 지식(prag_006) 어댑터가 준비되면
    #       settings·knowledge를 채워 build_report_context에 전달한다.
    context = build_report_context(keyword, fresh)
    # 출처는 화면 하단 블록에 따로 그리므로 본문에는 붙이지 않는다.
    body_markdown = generate_report(context, include_sources=False)
    return {
        "result": assist_result,
        "body_markdown": body_markdown,
        "sources": collect_sources(fresh),
        # 키워드가 주가/지수면 차트를 만든다(아니면 None). 네트워크 실패도 None.
        "chart": build_stock_chart(keyword),
    }


def _extract_lead(markdown_body: str) -> str:
    """보고서 본문에서 리드 문장(첫 요약 문장)을 뽑는다."""
    import re

    text = re.sub(r"^#+ .*$", "", markdown_body, flags=re.MULTILINE)
    text = " ".join(text.split())
    first = re.split(r"(?<=[.。!?])\s", text, maxsplit=1)
    return (first[0] if first else text)[:180]


def _render_source_rows(sources: list[dict[str, str]]) -> str:
    """출처 목록을 디자인의 .srcrow 형식으로 렌더링한다. 이미지가 있으면 썸네일을 붙인다."""
    rows = []
    for index, source in enumerate(sources, start=1):
        title = html.escape(str(source.get("title") or ""))
        url = html.escape(str(source.get("url") or ""))
        label = html.escape(str(source.get("label") or ""))
        image = str(source.get("image_url") or "")
        thumb = (
            f'<img src="{html.escape(image)}" alt="" loading="lazy" '
            f'style="width:56px;height:40px;object-fit:cover;border-radius:6px;flex-shrink:0;" '
            f'onerror="this.style.display=\'none\'">'
            if image
            else ""
        )
        rows.append(
            f'<div class="srcrow"><span class="no2">[{index}]</span>{thumb}'
            f'<div style="flex:1;"><div class="sn">{title}</div><div class="pub">{label}</div></div>'
            f'<span class="stp">{label}</span>'
            f'<a class="go" href="{url}" target="_blank">원문 열기 ↗</a></div>'
        )
    return "\n".join(rows)


def _render_chart(chart: dict[str, object] | None) -> str:
    """주가 차트가 있으면 figure로 렌더링한다(SVG는 신뢰된 내부 생성물이라 그대로 삽입)."""
    if not chart or not chart.get("chart_svg"):
        return ""
    name = html.escape(str(chart.get("name") or ""))
    symbol = html.escape(str(chart.get("symbol") or ""))
    return (
        '<figure class="fig" style="margin:0 0 18px;">'
        f'{chart["chart_svg"]}'
        f'<figcaption class="pmeta" style="margin-top:6px;">{name} ({symbol}) · 출처 Stooq 일별 종가</figcaption>'
        '</figure>'
    )


def _render_report_detail(
    keyword: str,
    body_markdown: str,
    sources: list[dict[str, str]],
    errors: list,
    chart: dict[str, object] | None = None,
) -> str:
    """AlphaCatcher report-detail 디자인으로 보고서 결과 페이지를 렌더링한다."""
    kw = html.escape(keyword)
    lead = html.escape(_extract_lead(body_markdown))
    body_html = _render_markdown(body_markdown)
    chart_html = _render_chart(chart)
    src_count = len(sources)
    src_rows = _render_source_rows(sources) or "<p class='pmeta'>표시할 출처가 없습니다.</p>"
    errors_html = "".join(
        f'<div class="dlead" style="color:var(--err)">{html.escape(str(e))}</div>' for e in errors
    )

    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{kw} 브리핑</title>
<style>{_DESIGN_CSS}</style>
</head>
<body>
<div class="page" data-theme="light"><div class="stage"><div class="app">
  <nav class="nav">
    <div class="logo"><span class="word">alphacatcher</span></div>
    <div class="spacer"></div>
  </nav>
  <div class="shell"><main class="reader">
    <div class="readbar"><a class="back" href="/report"><span class="ar">←</span>새 보고서</a><span class="rsp"></span></div>
    <article class="dcard">
      <div class="dhead">
        <span class="pav me">나</span>
        <div><div class="pname">{kw} 브리핑</div><div class="pmeta">방금 생성 · 수집 자료 종합</div></div>
        <span class="dpill">나만 보기</span>
      </div>
      <h1 class="dtitle">{kw} — 오늘의 브리핑</h1>
      <p class="dlead">{lead}</p>
      <div class="dmeta">
        <span>출처 <b>{src_count}건</b></span><span class="dot">·</span>
        <span>왜 나에게 왔나: 관심사 <b>‘{kw}’</b> 검색</span>
      </div>
      {errors_html}
      {chart_html}
      <div class="md">{body_html}</div>
    </article>
    <section class="block">
      <div class="bt">출처 <span class="cnt">{src_count}건</span></div>
      {src_rows}
    </section>
  </main></div>
</div></div></div>
</body></html>"""


@assistant_router.post("/report/generate", response_class=HTMLResponse)
async def report_generate(user_id: str = Form(...), keyword: str = Form(...)) -> str:
    """키워드로 최신 자료를 모아 개인화 보고서를 생성해 보여준다."""
    outcome = await run_in_threadpool(_run_report, keyword, user_id)
    result = outcome["result"]
    return _render_report_detail(
        keyword=str(result["keyword"]),
        body_markdown=str(outcome["body_markdown"]),
        sources=outcome["sources"],
        errors=result.get("errors", []),
        chart=outcome.get("chart"),
    )
