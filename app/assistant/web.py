"""키워드 비서 웹 라우터.

/ 에서 사용자 식별자와 키워드를 입력받아 YouTube 자막 요약, Reddit 게시글 요약,
최신·중복 제거 기사 URL을 함께 보여준다. YouTube는 사용자의 시청 이력을 반영해
개인화한다: 처음 조회하는 키워드는 입문성 영상까지 폭넓게 보여주고, 이미 조회한
적이 있으면 최근 영상 중 아직 보지 않은 영상만 남긴다. "봤다"는 판단은 실제로
영상 링크를 클릭했을 때만 기록한다(/watch 리다이렉트 경유).

실제 외부 호출(YouTube, Reddit, Google News RSS, Jina Reader)과 LLM 요약이
일어나므로 응답에 다소 시간이 걸린다.
"""

from __future__ import annotations

import html
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Form
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse

from agent.assistant import history
from agent.assistant.service import assist

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
최신 뉴스 URL을 중복 없이 모아줍니다. YouTube는 이전에 본 영상을 기억해뒀다가
다음에는 새 영상 위주로 보여줍니다.</p>
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
    """Reddit 게시글 요약 카드를 HTML로 렌더링한다."""
    if not items:
        return "<p class='note'>관련 게시글을 찾지 못했습니다.</p>"
    cards = []
    for item in items:
        title = html.escape(str(item.get("title") or ""))
        url = html.escape(str(item.get("url") or ""))
        subreddit = html.escape(str(item.get("subreddit") or ""))
        if item.get("summary"):
            body = f"<div class='summary'>{html.escape(str(item['summary']))}</div>"
        else:
            body = f"<div class='note'>{html.escape(str(item.get('note') or '요약 없음'))}</div>"
        cards.append(
            f"<div class='card'><a href='{url}' target='_blank'>{title}</a>"
            f"<div class='meta'>r/{subreddit}</div>{body}</div>"
        )
    return "\n".join(cards)


def _render_articles(items: list[dict[str, object]]) -> str:
    """어제 발행된 기사 URL 카드를 HTML로 렌더링한다."""
    if not items:
        return "<p class='note'>어제 발행된 기사를 찾지 못했습니다.</p>"
    cards = []
    for item in items:
        title = html.escape(str(item.get("title") or ""))
        url = html.escape(str(item.get("url") or ""))
        published = html.escape(str(item.get("published") or ""))
        snippet = html.escape(str(item.get("snippet") or ""))
        cards.append(
            f"<div class='card'><a href='{url}' target='_blank'>{title}</a>"
            f"<div class='meta'>{published}</div>"
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
<h2>👽 관련 Reddit 게시글 요약</h2>
{_render_reddit(result.get("reddit", []))}
<h2>📰 어제 기사 (중복 제거)</h2>
{_render_articles(result.get("articles", []))}
"""


@assistant_router.get("/watch")
async def watch_redirect(user_id: str, keyword: str, video_id: str, url: str, title: str = "") -> RedirectResponse:
    """영상 클릭을 시청 이력으로 기록한 뒤 실제 YouTube 페이지로 리다이렉트한다."""
    await run_in_threadpool(history.record_watch, user_id, keyword, video_id, title, url)
    return RedirectResponse(url, status_code=302)
