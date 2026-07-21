"""키워드 비서 웹 라우터.

`/` 에서 사용자 식별자와 키워드를 입력받아 `/search`로 제출하면, 신규 선별
파이프라인(agent.assistant.api.assist_daily_agent)을 한 번 실행하고 결과를 한
페이지에 두 칸으로 나누어 보여준다.

  ① 수집·선별 내역 — 단계별 수집/제외 건수, 선정된 아이템별 점수 분해
     (유사도 × 신선도 × 소스가중 × 클러스터부스트 = 최종점수)와 실제 수집한
     출처 링크, 제외 사유 로그. 임계값 튜닝·동작 확인용이다.
  ② 보고서 — 워터폴 판정(당일/주간/개념 정리) 결과 Markdown 보고서.

실제 외부 호출(뉴스 RSS·YouTube·Reddit·Jina)과 OpenAI 임베딩·요약이 일어나므로
응답에 다소 시간이 걸리고 비용이 발생한다.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable

from fastapi import APIRouter, Form
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse

from agent.assistant.api import assist_daily_agent, collect_window_days

assistant_router = APIRouter(tags=["assistant"])

_PAGE_STYLE = """
<style>
  body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; max-width: 900px;
         margin: 2rem auto; padding: 0 1rem; color: #1c1c1e; line-height: 1.6; }
  h1 { font-size: 1.5rem; } h2 { font-size: 1.15rem; margin-top: 1.4rem; }
  a { color: #1a56c4; text-decoration: none; }
  label { display: block; font-size: .85rem; color: #6a6a72; margin: .8rem 0 .3rem; }
  input { width: 100%; padding: .7rem; font-size: 1rem; box-sizing: border-box;
          border: 1px solid #ccc; border-radius: 8px; }
  button { margin-top: 1rem; padding: .7rem 1.5rem; font-size: 1rem; border: 0;
           border-radius: 8px; background: #d6402c; color: #fff; cursor: pointer; }
  .banner { background:#eef4ff; border:1px solid #cfe0ff; border-radius:8px; padding:.6rem .9rem;
            font-size:.9rem; color:#234; }
  .err { background:#fff1f0; border:1px solid #ffccc7; border-radius:8px; padding:.5rem .8rem;
         font-size:.85rem; color:#a8071a; margin:.4rem 0; }
  .section { border:1px solid #e3e3e8; border-radius:12px; padding:1rem 1.2rem; margin:1.2rem 0;
             background:#fafafd; }
  .section > .sec-title { font-size:1.1rem; font-weight:700; margin:0 0 .6rem;
                          padding-bottom:.5rem; border-bottom:1px solid #e8e8ee; }
  .card { border:1px solid #e3e3e8; border-radius:10px; padding:.8rem 1rem; margin:.7rem 0;
          background:#fff; }
  .card .title { font-weight:600; font-size:1rem; }
  .badge { display:inline-block; font-size:.72rem; font-weight:600; padding:.1rem .5rem;
           border-radius:999px; vertical-align:middle; margin-left:.4rem; }
  .badge.new { background:#e6f4ea; color:#1e7d34; }
  .badge.update { background:#fff4e5; color:#a86400; }
  .badge.mode { background:#eef0ff; color:#3a44b0; margin-left:0; }
  .badge.cold { background:#eef2f5; color:#556; margin-left:.4rem; }
  .score { float:right; font-weight:700; color:#d6402c; }
  .breakdown { font-size:.82rem; color:#6a6a72; margin:.35rem 0; font-variant-numeric:tabular-nums; }
  .metaline { font-size:.82rem; color:#8a8a92; margin:.2rem 0; }
  .srclist { margin:.4rem 0 0; padding-left:1.1rem; font-size:.88rem; }
  .srclist li { margin:.15rem 0; }
  .trace li { margin:.5rem 0; line-height:1.5; }
  .trace li strong { color:#3a44b0; }
  .badge.trace-ok { background:#e6f4ea; color:#1e7d34; }
  .badge.trace-retry { background:#fff4e5; color:#a86400; }
  .badge.trace-stop { background:#eef2f5; color:#556; }
  .badge.trace-failed { background:#fff1f0; color:#a8071a; }
  .trace .metaline { font-size:.76rem; }
  .trace .err { margin:.25rem 0 0; font-size:.78rem; }
  code { background:#eef0f3; padding:.05rem .35rem; border-radius:5px; font-size:.85em; }
  .stype { color:#8a8a92; font-size:.78rem; }
  details { margin-top:.8rem; }
  summary { cursor:pointer; font-size:.9rem; color:#6a6a72; }
  table.excl { width:100%; border-collapse:collapse; font-size:.82rem; margin-top:.5rem; }
  table.excl th, table.excl td { text-align:left; padding:.3rem .5rem; border-bottom:1px solid #eee;
                                 vertical-align:top; }
  table.excl th { color:#6a6a72; font-weight:600; }
  .md h1 { font-size:1.3rem; } .md h2 { font-size:1.08rem; }
  .empty { color:#8a8a92; font-size:.9rem; }
</style>
"""

# 워터폴 모드 라벨.
_MODE_LABELS = {
    "daily": "당일 신규",
    "weekly": "주간 트렌드 요약",
    "evergreen": "개념 정리",
}

# 소스 타입 라벨.
_SOURCE_TYPE_LABELS = {"news": "뉴스", "youtube": "YouTube", "reddit": "Reddit"}

# 발행일 추출 방법 라벨(어느 단계에서 날짜를 얻었는지 보여준다).
_DATE_METHOD_LABELS = {
    "pub_date": "RSS 발행일",
    "html_meta": "메타태그",
    "url_path": "URL 패턴",
    "body_parse": "본문 파싱",
    "first_seen": "최초 발견일(대용)",
    "none": "미상",
}

# 제외 단계 라벨.
_STAGE_LABELS = {
    "basic_filter": "기초 필터",
    "similarity_filter": "유사도 필터",
    "dedup": "중복 검사",
    "threshold": "임계값",
}

# pipeline._exclude가 남기는 원인 코드(예: "outside_window", "low_similarity(0.42 < 0.50)")를
# 사람이 읽는 한국어 문장으로 바꾼다. (정규식, 설명 생성 함수) 순서 목록이며, 위에서부터 매칭한다.
_REASON_RULES: list[tuple[re.Pattern[str], Callable[[re.Match[str]], str]]] = [
    (re.compile(r"^no_url$"), lambda m: "링크 정보가 없는 항목이라 제외"),
    (re.compile(r"^duplicate_url$"), lambda m: "같은 링크가 중복 수집돼 제외"),
    (re.compile(r"^url_already_collected$"), lambda m: "예전에 이미 수집한 링크라 제외(재수집 안 함)"),
    (re.compile(r"^too_short$"), lambda m: "본문이 너무 짧아 분석할 내용이 없어 제외"),
    (
        re.compile(r"^outside_window$"),
        lambda m: f"발행일이 수집 기간(최근 {collect_window_days()}일)보다 오래돼 제외",
    ),
    (
        re.compile(r"^low_similarity\(([\d.]+)\s*<\s*([\d.]+)\)$"),
        lambda m: f"키워드와 관련성이 낮아 제외 (관련도 {m.group(1)} · 이번 검색 기준 {m.group(2)} 미달)",
    ),
    (
        re.compile(r"^already_reported\(([\d.]+),\s*기존:\s*(.+)\)$"),
        lambda m: f"최근 보고서에 이미 실은 소식과 비슷해 제외 (유사도 {m.group(1)} · 이전 글 “{m.group(2)}”)",
    ),
    (
        re.compile(r"^below_threshold\(([\d.]+)\s*<\s*([\d.]+)\)$"),
        lambda m: f"점수가 이번 검색 기준({m.group(2)})에 못 미쳐 제외 (점수 {m.group(1)})",
    ),
]


def _friendly_reason(reason: str) -> str:
    """제외 사유 원인 코드를 사람이 읽는 한국어 문장으로 바꾼다.

    매칭되는 규칙이 없으면(알려지지 않은 신규 사유) 원문 코드를 그대로 보여준다
    (숨기지 않고 그대로 노출해, 새 사유가 생겨도 조용히 사라지지 않게 한다).
    """
    for pattern, describe in _REASON_RULES:
        match = pattern.match(reason)
        if match:
            return describe(match)
    return reason


def _form_html(user_id: str = "") -> str:
    """사용자 식별자를 미리 채운 키워드 입력 폼을 만든다."""
    user_id_value = html.escape(user_id)
    return f"""
<!doctype html>
<meta charset="utf-8">
<title>키워드 비서 AI</title>
{_PAGE_STYLE}
<h1>🔎 키워드 비서 AI</h1>
<p class="banner">이름과 키워드를 입력하면 최근 자료를 수집해 유사도·신선도·소스 신뢰도로
점수를 매기고, 중복을 걸러 하나의 일간 브리핑으로 정리합니다. 다음 페이지에서 수집·선별
내역과 보고서를 함께 보여줍니다.</p>
<form method="post" action="/search">
  <label for="user_id">이름 / 아이디</label>
  <input id="user_id" name="user_id" required placeholder="예: minji" value="{user_id_value}">
  <label for="keyword">키워드</label>
  <input id="keyword" name="keyword" required placeholder="예: 전고체 배터리" autofocus>
  <button type="submit">수집 &amp; 브리핑 생성</button>
</form>
"""


@assistant_router.get("/", response_class=HTMLResponse)
async def assistant_form(user_id: str = "") -> str:
    """키워드 입력 폼 페이지를 반환한다. user_id가 주어지면 미리 채운다."""
    return _form_html(user_id)


def _render_markdown(text: str) -> str:
    """보고서 Markdown을 가벼운 규칙으로 HTML로 변환한다(제목·불릿·굵게·인용).

    외부 라이브러리 없이 최소한만 처리하고, 그 외는 그대로 표시한다. 인용(>)은
    워터폴 폴백 라벨("오늘 신규 소식 없음 — …")을 강조 배너로 보여주는 데 쓴다.
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
        if line.startswith("&gt; "):
            close_list()
            out.append(f'<p class="banner">{line[5:]}</p>')
        elif line.startswith("### "):
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


def _render_sources(sources: list[dict[str, object]]) -> str:
    """아이템(클러스터)에 묶인 실제 수집 출처 링크 목록을 렌더링한다."""
    if not sources:
        return ""
    items = []
    for source in sources:
        url = html.escape(str(source.get("url") or ""))
        title = html.escape(str(source.get("title") or url))
        label = _SOURCE_TYPE_LABELS.get(str(source.get("source_type") or ""), "링크")
        items.append(
            f'<li><span class="stype">[{label}]</span> '
            f'<a href="{url}" target="_blank">{title}</a></li>'
        )
    return f'<ul class="srclist">{"".join(items)}</ul>'


def _render_daily_item(item: dict[str, object]) -> str:
    """당일 선정 아이템 하나를 점수 분해·출처와 함께 카드로 렌더링한다."""
    title = html.escape(str(item.get("title") or ""))
    status = str(item.get("status") or "신규")
    badge_class = "update" if status == "업데이트" else "new"
    score = float(item.get("score") or 0.0)

    detail = dict(item.get("score_detail") or {})
    breakdown = (
        f"유사도 {float(detail.get('similarity', 0)):.3f} × "
        f"신선도 {float(detail.get('freshness', 0)):.3f} × "
        f"소스가중 {float(detail.get('source_weight', 0)):.2f} × "
        f"클러스터 {float(detail.get('cluster_boost', 0)):.2f} "
        f"= <strong>{score:.3f}</strong>"
    )

    published = html.escape(str(item.get("published") or "")[:10])
    method = _DATE_METHOD_LABELS.get(str(item.get("published_method") or ""), "")
    size = int(item.get("cluster_size") or 1)
    meta_parts = [f"클러스터 {size}건"]
    if published:
        meta_parts.append(f"발행일 {published}" + (f" ({method})" if method else ""))
    content_type = str(detail.get("content_type") or "")
    if content_type:
        meta_parts.append("에버그린" if content_type == "evergreen" else "뉴스")

    return (
        '<div class="card">'
        f'<span class="score">{score:.3f}</span>'
        f'<div class="title">{title}<span class="badge {badge_class}">{status}</span></div>'
        f'<div class="breakdown">{breakdown}</div>'
        f'<div class="metaline">{html.escape(" · ".join(meta_parts))}</div>'
        f'{_render_sources(list(item.get("sources") or []))}'
        "</div>"
    )


def _render_weekly_item(item: dict[str, object]) -> str:
    """주간 트렌드 폴백 이슈 하나를 링크·점수와 함께 카드로 렌더링한다."""
    title = html.escape(str(item.get("title") or ""))
    url = html.escape(str(item.get("url") or ""))
    score = float(item.get("score") or 0.0)
    title_html = f'<a href="{url}" target="_blank">{title}</a>' if url else title
    return (
        '<div class="card">'
        f'<span class="score">{score:.3f}</span>'
        f'<div class="title">{title_html}</div>'
        "</div>"
    )


def _render_exclusions(log: dict[str, object]) -> str:
    """단계별 제외 문서와 사유를 접이식 표로 렌더링한다(임계값 튜닝용)."""
    exclusions = list(log.get("exclusions") or [])
    if not exclusions:
        return ""
    rows = []
    for entry in exclusions:
        stage = _STAGE_LABELS.get(str(entry.get("stage") or ""), str(entry.get("stage") or ""))
        reason = html.escape(_friendly_reason(str(entry.get("reason") or "")))
        title = html.escape(str(entry.get("title") or "")[:60])
        rows.append(
            f"<tr><td>{html.escape(stage)}</td><td>{reason}</td><td>{title}</td></tr>"
        )
    return (
        f"<details><summary>제외 내역 {len(exclusions)}건 보기</summary>"
        '<table class="excl"><thead><tr><th>단계</th><th>사유</th><th>문서</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></details>"
    )


def _render_pipeline_section(result: dict[str, object]) -> str:
    """① 수집·선별 내역 섹션을 만든다(요약 배너 + 선정 아이템 + 제외 로그)."""
    mode = str(result.get("mode") or "daily")
    log = dict(result.get("log") or {})
    items = list(result.get("items") or [])

    mode_badge = f'<span class="badge mode">{_MODE_LABELS.get(mode, mode)}</span>'
    cold_badge = '<span class="badge cold">콜드 스타트</span>' if result.get("cold_start") else ""

    counts = (
        f"수집 {int(log.get('collected', 0))}건 → "
        f"기초필터 후 {int(log.get('after_basic_filter', 0))} → "
        f"유사도필터 후 {int(log.get('after_similarity_filter', 0))} → "
        f"클러스터 {int(log.get('clusters', 0))}개 → "
        f"선정 {len(items) if mode != 'evergreen' else 0}개"
    )

    if mode == "daily":
        cards = "\n".join(_render_daily_item(item) for item in items)
    elif mode == "weekly":
        cards = (
            '<p class="metaline">당일 기준 통과 아이템이 없어, 최근 7일 수집분 중 '
            "최고 점수 이슈로 전환했습니다.</p>"
            + "\n".join(_render_weekly_item(item) for item in items)
        )
    else:  # evergreen
        cards = (
            '<p class="empty">당일 신규 소식도 최근 주간 수집분도 없어, 주제의 핵심 개념 '
            "정리로 전환했습니다. 수집·선정된 항목은 없습니다.</p>"
        )

    return (
        '<div class="section">'
        f'<div class="sec-title">① 수집·선별 내역 {mode_badge}{cold_badge}</div>'
        f'<p class="metaline">{html.escape(counts)}</p>'
        f"{cards}"
        f"{_render_exclusions(log)}"
        "</div>"
    )


# trace 이벤트 status → 화면 뱃지 라벨·클래스.
_TRACE_STATUS_BADGES = {
    "ok": ("정상", "ok"),
    "retry": ("재시도", "retry"),
    "stop": ("중단", "stop"),
    "failed": ("실패", "failed"),
}


def _render_trace_step(step: object) -> str:
    """구조화된 trace 이벤트 하나를 목록 항목으로 렌더링한다.

    이벤트는 {node, status, reason, query, errors, duration_ms, message} 구조다.
    message의 '라벨: 본문'에서 라벨을 굵게 하고, status 뱃지와 원인 코드·소요
    시간·오류를 함께 보여줘 감사(audit) 가능하게 한다.
    """
    if not isinstance(step, dict):
        # 구조화 이전 형식(문자열)도 깨지지 않게 처리한다.
        text = str(step)
        label, sep, body = text.partition(": ")
        inner = (
            f"<strong>{html.escape(label)}:</strong> {html.escape(body)}"
            if sep
            else html.escape(text)
        )
        return f"<li>{inner}</li>"

    message = str(step.get("message") or "")
    label, sep, body = message.partition(": ")
    inner = (
        f"<strong>{html.escape(label)}:</strong> {html.escape(body)}"
        if sep
        else html.escape(message)
    )

    status = str(step.get("status") or "")
    badge_text, badge_class = _TRACE_STATUS_BADGES.get(status, (status, "stop"))
    badge = (
        f'<span class="badge trace-{html.escape(badge_class)}">{html.escape(badge_text)}</span>'
        if badge_text
        else ""
    )

    meta_parts = []
    if step.get("reason"):
        meta_parts.append(f"원인 {step['reason']}")
    duration = int(step.get("duration_ms") or 0)
    if duration:
        meta_parts.append(f"{duration}ms")
    meta = (
        f'<div class="metaline">{html.escape(" · ".join(meta_parts))}</div>' if meta_parts else ""
    )

    errors = list(step.get("errors") or [])
    errors_html = "".join(
        f'<div class="err">{html.escape(str(error))}</div>' for error in errors
    )

    return f"<li>{inner}{badge}{meta}{errors_html}</li>"


def _render_agent_section(result: dict[str, object]) -> str:
    """⓪ 에이전트 판단 과정 섹션을 만든다(검색어 계획·재구성·재시도 판단·보고 결정 흐름).

    각 단계가 무엇을, 왜 했는지(어떤 검색어로 바뀌었는지, 재시도할지 말지와 그
    원인 코드가 무엇인지, 오류가 있었는지)를 구조화 이벤트 그대로 보여준다.
    검색어를 한 번도 재구성하지 않았으면 "시도한 검색어" 줄은 생략한다.
    """
    trace = list(result.get("agent_trace") or [])
    if not trace:
        return ""
    attempts = list(result.get("attempts") or [])
    steps = "".join(_render_trace_step(step) for step in trace)
    tried = ""
    if len(attempts) > 1:
        chips = " → ".join(f"<code>{html.escape(str(q))}</code>" for q in attempts)
        tried = f'<p class="metaline">시도한 검색어: {chips}</p>'
    return (
        '<div class="section">'
        '<div class="sec-title">⓪ 에이전트 판단 과정</div>'
        f"{tried}"
        f'<ol class="srclist trace">{steps}</ol>'
        "</div>"
    )


def _render_report_section(result: dict[str, object]) -> str:
    """② 보고서 섹션을 만든다(워터폴 판정 결과 Markdown 렌더링)."""
    body = str(result.get("report_markdown") or "")
    body_html = _render_markdown(body) if body.strip() else '<p class="empty">보고서를 생성하지 못했습니다.</p>'
    return (
        '<div class="section">'
        '<div class="sec-title">② 보고서</div>'
        f'<div class="md">{body_html}</div>'
        "</div>"
    )


def _render_results(result: dict[str, object]) -> str:
    """검색 결과 전체 페이지(수집·선별 내역 + 보고서)를 렌더링한다."""
    from urllib.parse import quote, urlencode

    keyword = html.escape(str(result.get("keyword") or ""))
    back_link = f"/?{urlencode({'user_id': str(result.get('user_id') or '')}, quote_via=quote)}"
    errors_html = "".join(
        f"<div class='err'>{html.escape(str(err))}</div>" for err in result.get("errors", [])
    )

    return f"""
<!doctype html>
<meta charset="utf-8">
<title>{keyword} — 키워드 비서</title>
{_PAGE_STYLE}
<h1>🔎 “{keyword}” 브리핑</h1>
<p><a href="{back_link}">← 다른 키워드로 검색</a></p>
{errors_html}
{_render_agent_section(result)}
{_render_pipeline_section(result)}
{_render_report_section(result)}
"""


@assistant_router.post("/search", response_class=HTMLResponse)
async def assistant_search(user_id: str = Form(...), keyword: str = Form(...)) -> str:
    """키워드로 리서치 에이전트를 실행하고 판단 과정·수집 내역·보고서를 함께 보여준다."""
    result = await run_in_threadpool(assist_daily_agent, keyword, user_id=user_id)
    return _render_results(result)
