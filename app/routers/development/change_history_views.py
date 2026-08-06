"""변경점(Delta) 추적 웹 테스트 페이지(/changeHistory) 라우터.

토글을 켜고 끄며 같은 주제로 리포트를 만들어 보고, 결과를 네 섹션으로 나눠
확인하는 개발 전용 화면이다. 실행 경로는 개발 API
(`POST /dev/users/{user_id}/report-generations`)와 **완전히 같다** — Job을
멱등 등록하고 AgentWorkflowService로 그래프를 돌린다. 화면만 다르고 코드
경로가 갈라지지 않아야 여기서 본 결과가 실제 발행 결과와 같다.

**화면 구분은 렌더링일 뿐이다.** 아래 섹션 분리와 before/after 강조는 저장된
markdown **한 장**을 `## ` 헤더로 쪼개 보여주는 것이며, 실제로 저장·전송되는
데이터는 그 markdown 문자열 하나뿐이다(원문도 페이지 아래에 그대로 싣는다).

개발 API와 같은 게이트(require_development_access)를 쓰므로 local/test 환경에서
명시적으로 활성화했을 때만 접근할 수 있다. 사람이 보는 화면이라 OpenAPI 문서에는
올리지 않는다.
"""

from __future__ import annotations

import html
import re
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse

from app.dependencies import get_agent_workflow_service, get_mvp_service
from app.routers.development.routes import require_development_access
from app.schemas.mvp import GenerationRequest
from app.services.agent_workflows import AgentWorkflowService
from app.services.mvp import AgentApiMvpService

router = APIRouter(dependencies=[Depends(require_development_access)])

CHANGE_HISTORY_PATH = "/changeHistory"

# 조립 단계가 붙이는 섹션 헤더. agent/change_history/features/assembly.py의
# 상수와 같은 값이며, 화면은 저장된 markdown을 이 헤더로 쪼개 보여준다.
_SECTION_PATTERN = re.compile(r"^## (.+)$", re.MULTILINE)
# 주요 업데이트 안의 소제목(달라진 사실 / 새로 확인된 사실).
_SUBSECTION_PATTERN = re.compile(r"^###\s+(.+)$")
# 갱신 팩트 표기 `이전값` → `오늘값` 을 찾아 화면에서 대비시킨다.
_BEFORE_AFTER_PATTERN = re.compile(r"`([^`]*)`\s*→\s*`([^`]*)`")
# 값 하나만 있는 표기(새로 확인된 사실). 화면에서 today 색으로 강조한다.
_SINGLE_VALUE_PATTERN = re.compile(r"`([^`]*)`")
# 굵게 표기한 대상 이름(**주체 · 속성**).
_BOLD_PATTERN = re.compile(r"\*\*([^*]+)\*\*")

_PAGE_STYLE = """
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, "Apple SD Gothic Neo", "Segoe UI", sans-serif;
    margin: 0 auto; max-width: 960px; padding: 2rem 1.25rem 4rem; line-height: 1.6;
  }
  h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }
  .subtitle { color: #667; margin-bottom: 1.5rem; font-size: 0.9rem; }
  form { border: 1px solid rgba(127,127,127,0.35); border-radius: 10px; padding: 1.25rem 1.5rem; }
  label { display: block; font-size: 0.85rem; color: #667; margin: 0.7rem 0 0.25rem; }
  input[type=text] {
    width: 100%; padding: 0.6rem; font-size: 1rem; box-sizing: border-box;
    border: 1px solid rgba(127,127,127,0.5); border-radius: 8px; background: transparent;
    color: inherit;
  }
  .toggle { display: flex; align-items: center; gap: 0.5rem; margin-top: 1rem; font-size: 0.95rem; }
  button {
    margin-top: 1.2rem; padding: 0.65rem 1.5rem; font-size: 1rem; border: 0;
    border-radius: 8px; background: #d6402c; color: #fff; cursor: pointer;
  }
  section {
    border: 1px solid rgba(127,127,127,0.35); border-radius: 10px;
    padding: 1rem 1.5rem; margin: 1.5rem 0;
  }
  section h2 { font-size: 1.1rem; margin: 0 0 0.5rem; }
  section h3 {
    font-size: 0.95rem; margin: 1.2rem 0 0.4rem; padding: 0.25rem 0.6rem;
    border-radius: 6px; display: inline-block;
  }
  section h3.changed { background: rgba(214, 64, 44, 0.12); color: #b3400f; }
  section h3.fresh { background: rgba(30, 125, 52, 0.12); color: #1e7d34; }
  .meta { font-size: 0.85rem; color: #667; }
  .meta code { font-size: 0.85rem; }
  .before {
    text-decoration: line-through; opacity: 0.65;
    background: rgba(127,127,127,0.12); padding: 0.05rem 0.35rem; border-radius: 4px;
  }
  .arrow { margin: 0 0.4rem; color: #b3400f; font-weight: 700; }
  .after {
    font-weight: 700; color: #b3400f;
    background: rgba(214, 64, 44, 0.1); padding: 0.05rem 0.35rem; border-radius: 4px;
  }
  .value {
    font-weight: 600; color: #1e7d34;
    background: rgba(30, 125, 52, 0.1); padding: 0.05rem 0.35rem; border-radius: 4px;
  }
  .badge {
    display: inline-block; font-size: 0.72rem; font-weight: 700; padding: 0.1rem 0.5rem;
    border-radius: 999px; margin-right: 0.4rem;
  }
  .badge.on { background: #e6f4ea; color: #1e7d34; }
  .badge.off { background: #eceff3; color: #55606e; }
  pre { white-space: pre-wrap; word-break: break-word; font-size: 0.85rem;
        background: rgba(127,127,127,0.12); padding: 1rem; border-radius: 8px; }
  .err { border-color: #ffccc7; background: rgba(255,77,79,0.08); }
  @media (prefers-color-scheme: dark) {
    .subtitle, .meta, label { color: #99a; }
    .after, .arrow { color: #ff9d6b; }
    .value { color: #7bd694; }
    section h3.changed { color: #ff9d6b; }
    section h3.fresh { color: #7bd694; }
  }
"""


def split_report_sections(markdown: str) -> list[tuple[str, str]]:
    """저장된 markdown 한 장을 `## ` 헤더 단위로 쪼갠다.

    화면 표시 전용 함수다. 원본 문자열을 자르기만 하므로, 여기서 보이는 내용은
    항상 저장·전송되는 본문과 같다.

    Args:
        markdown: 조립 단계가 만든 보고서 본문

    Returns:
        (섹션 제목, 섹션 본문) 목록. 헤더가 없으면 전체를 한 덩어리로 돌려준다.
    """
    matches = list(_SECTION_PATTERN.finditer(markdown or ""))
    if not matches:
        return [("본문", (markdown or "").strip())]
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections.append((match.group(1).strip(), markdown[start:end].strip()))
    return sections


def highlight_before_after(escaped_line: str) -> str:
    """`이전값` → `오늘값` 표기를 화면에서 대비되게 감싼다.

    이미 HTML escape된 문자열을 받아 태그만 덧붙인다. 값 자체는 바꾸지 않는다 —
    화면에 보이는 before/after는 저장된 본문의 값 그대로여야 한다.

    두 값이 짝으로 있으면 이전/오늘로 대비시키고, 값이 하나뿐이면(새로 확인된
    사실) 오늘 값으로만 강조한다.
    """
    marked, changed = _BEFORE_AFTER_PATTERN.subn(
        lambda match: (
            f'<span class="before">{match.group(1)}</span>'
            f'<span class="arrow">→</span>'
            f'<span class="after">{match.group(2)}</span>'
        ),
        escaped_line,
    )
    if changed:
        return marked
    return _SINGLE_VALUE_PATTERN.sub(
        lambda match: f'<span class="value">{match.group(1)}</span>', escaped_line
    )


def _render_line(raw: str) -> str:
    """본문 한 줄을 HTML로 만든다(대상 이름 굵게 + 값 강조)."""
    escaped = html.escape(raw)
    marked = highlight_before_after(escaped)
    return _BOLD_PATTERN.sub(lambda match: f"<strong>{match.group(1)}</strong>", marked)


def _render_section(title: str, body: str) -> str:
    """섹션 하나를 HTML로 만든다.

    `### ` 소제목(달라진 사실 / 새로 확인된 사실)은 소제목으로 렌더해, 갱신과
    신규가 화면에서도 갈라 보이게 한다.
    """
    parts: list[str] = [f"    <h2>{html.escape(title)}</h2>"]
    for raw in body.splitlines():
        if not raw.strip():
            continue
        subsection = _SUBSECTION_PATTERN.match(raw.strip())
        if subsection:
            kind = "changed" if "달라진" in subsection.group(1) else "fresh"
            parts.append(
                f'    <h3 class="{kind}">{html.escape(subsection.group(1))}</h3>'
            )
            continue
        parts.append(f"    <p>{_render_line(raw)}</p>")
    return "  <section>\n" + "\n".join(parts) + "\n  </section>"


def _render_form(user_id: str, topic: str, enabled: bool) -> str:
    """실행 폼을 HTML로 만든다."""
    checked = " checked" if enabled else ""
    return f"""
  <form method="post" action="{CHANGE_HISTORY_PATH}">
    <label for="user_id">사용자 ID</label>
    <input type="text" id="user_id" name="user_id" value="{html.escape(user_id)}" required>
    <label for="topic">주제</label>
    <input type="text" id="topic" name="topic" value="{html.escape(topic)}" required>
    <div class="toggle">
      <input type="checkbox" id="change_history_enabled" name="change_history_enabled"
             value="on"{checked}>
      <label for="change_history_enabled" style="margin:0;color:inherit;">
        변경점(Delta) 추적 사용 — 끄면 기존 생성 경로로 실행됩니다
      </label>
    </div>
    <button type="submit">실행</button>
  </form>"""


def _render_result(result: dict[str, Any], enabled: bool) -> str:
    """실행 결과를 섹션별 화면과 원문으로 만든다."""
    body = str(result.get("body") or "")
    badge = (
        '<span class="badge on">토글 ON · 변경점 추적</span>'
        if enabled
        else '<span class="badge off">토글 OFF · 기존 생성</span>'
    )
    sections = "\n".join(
        _render_section(title, content) for title, content in split_report_sections(body)
    )
    citations = result.get("citations") or []
    return f"""
  <p class="meta">{badge}
    <code>{html.escape(str(result.get("content_id") or ""))}</code> ·
    v{html.escape(str(result.get("version") or ""))} ·
    인용 {len(citations)}건</p>
  <section>
    <h2>{html.escape(str(result.get("title") or "(제목 없음)"))}</h2>
    <p>{html.escape(str(result.get("summary") or ""))}</p>
  </section>
{sections}
  <section>
    <h2>저장·전송되는 실제 데이터 (markdown 1장)</h2>
    <p class="meta">위 섹션 구분은 이 문자열을 헤더로 쪼개 보여준 것일 뿐입니다.</p>
    <pre>{html.escape(body)}</pre>
  </section>"""


def _render_page(
    *,
    user_id: str = "",
    topic: str = "",
    enabled: bool = True,
    result: dict[str, Any] | None = None,
    error: str = "",
) -> str:
    """전체 페이지 HTML을 만든다."""
    blocks = [_render_form(user_id, topic, enabled)]
    if error:
        blocks.append(
            f'  <section class="err"><h2>실행 실패</h2><p>{html.escape(error)}</p></section>'
        )
    if result is not None:
        blocks.append(_render_result(result, enabled))
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>변경점(Delta) 추적 테스트</title>
  <style>{_PAGE_STYLE}</style>
</head>
<body>
  <h1>변경점(Delta) 추적 테스트</h1>
  <p class="subtitle">개발 API와 같은 경로로 리포트를 만들고 결과를 확인합니다.
  실제 LLM·외부 수집 비용이 발생합니다.</p>
{"".join(blocks)}
</body>
</html>"""


@router.get(CHANGE_HISTORY_PATH, response_class=HTMLResponse, include_in_schema=False)
async def show_change_history_page() -> HTMLResponse:
    """토글과 실행 폼이 있는 변경점 추적 테스트 페이지를 반환한다."""
    return HTMLResponse(_render_page())


@router.post(CHANGE_HISTORY_PATH, response_class=HTMLResponse, include_in_schema=False)
async def run_change_history_page(
    user_id: str = Form(...),
    topic: str = Form(...),
    change_history_enabled: str = Form(default=""),
    jobs: AgentApiMvpService = Depends(get_mvp_service),
    workflows: AgentWorkflowService = Depends(get_agent_workflow_service),
) -> HTMLResponse:
    """토글 값을 실어 리포트를 한 번 생성하고 결과를 네 섹션으로 보여준다.

    실행할 때마다 새 멱등 키를 써서 같은 주제도 다시 돌릴 수 있게 한다 —
    토글 ON/OFF를 번갈아 비교하는 것이 이 페이지의 목적이기 때문이다.
    """
    enabled = bool(change_history_enabled)
    payload = GenerationRequest(
        idempotency_key=f"change-history-page:{uuid4()}",
        topic=topic,
        content_type="interest_news_card",
        language="ko",
        change_history_enabled=enabled,
    )
    try:
        accepted = await jobs.submit_generation(
            user_id=user_id, payload=payload, request_id=str(uuid4())
        )
        run = await workflows.run_job(
            accepted.job_id,
            expected_job_type="report_generation",
            expected_user_id=user_id,
        )
    except Exception as error:  # noqa: BLE001 — 개발 화면은 실패 사유를 그대로 보여준다
        return HTMLResponse(
            _render_page(
                user_id=user_id, topic=topic, enabled=enabled, error=str(error)
            )
        )
    if run.status != "completed":
        return HTMLResponse(
            _render_page(
                user_id=user_id,
                topic=topic,
                enabled=enabled,
                error=f"Job이 완료되지 않았습니다: {run.status} ({run.failed_stage or '-'})",
            )
        )
    return HTMLResponse(
        _render_page(
            user_id=user_id, topic=topic, enabled=enabled, result=dict(run.result)
        )
    )
