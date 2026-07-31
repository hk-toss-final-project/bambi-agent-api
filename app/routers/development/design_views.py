"""UI/UX 디자인 시안 페이지(/dev/design) 라우터.

관심사 화면과 리포트 피드백의 재설계 시안을 팀이 브라우저로 열어 볼 수 있게
제공한다. HTML·CSS·JS 본문은 templates/ 아래 파일이 소유하고, 파이썬은 목록과
파일 로드만 담당한다(app/wiki_graph/page.py와 같은 방식).

시안은 정적 파일이라 서버 없이 브라우저로 직접 열어도 동작한다. 외부 CDN을
쓰지 않으므로 오프라인에서도 그대로 렌더된다.

개발 API와 같은 게이트(require_development_access)를 쓰므로 local/test 환경에서
명시적으로 활성화했을 때만 접근할 수 있다. 사람이 보는 화면이라 OpenAPI 문서에는
올리지 않는다.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, status
from fastapi.responses import HTMLResponse

from app.exceptions import AgentApiError, ErrorDetail
from app.routers.development.routes import require_development_access

router = APIRouter(dependencies=[Depends(require_development_access)])

_TEMPLATE_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True, slots=True)
class DesignPage:
    """디자인 시안 한 건의 목록 정보와 템플릿 파일 이름."""

    slug: str
    title: str
    description: str
    template: str


# 시안을 추가하면 여기에 한 줄 등록하고 templates/에 HTML을 둔다.
_DESIGN_PAGES: tuple[DesignPage, ...] = (
    DesignPage(
        slug="interest-feedback",
        title="관심사·피드백 프로토타입",
        description=(
            "사용자 입장에서 직접 써보는 시안. 카드를 얼마나 읽었는지(열람·체류·"
            "스크롤 깊이)를 실제로 측정해 「이거 말고」의 대체 축을 사유 질문 없이 "
            "추론한다. 오른쪽 관측 패널에서 시스템이 읽은 값을 그대로 확인할 수 있다."
        ),
        template="interest_feedback_prototype.html",
    ),
    DesignPage(
        slug="interest-feedback-rationale",
        title="관심사·피드백 재설계 근거",
        description=(
            "위 시안이 왜 이렇게 나왔는지의 설계 메모. 관심사 화면에서 조작 장치를 "
            "걷어낸 이유, 축 추론 규칙, 신호 설계, 그리고 착수 전에 먼저 막아야 하는 "
            "선결 과제를 코드 근거와 함께 정리했다."
        ),
        template="interest_feedback_rationale.html",
    ),
)

_PAGE_STYLE = """
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, "Apple SD Gothic Neo", "Segoe UI", sans-serif;
    margin: 0 auto; max-width: 860px; padding: 2rem 1.25rem 4rem; line-height: 1.7;
  }
  h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }
  .subtitle { color: #667; margin-bottom: 2rem; }
  section {
    border: 1px solid rgba(127, 127, 127, 0.35); border-radius: 10px;
    padding: 1.25rem 1.5rem; margin-bottom: 1.25rem;
  }
  section h2 { font-size: 1.15rem; margin: 0 0 0.25rem; }
  section h2 a { color: inherit; }
  .description { color: #667; font-size: 0.9rem; margin: 0; }
  @media (prefers-color-scheme: dark) {
    .subtitle, .description { color: #99a; }
  }
"""


def get_design_page(slug: str) -> DesignPage | None:
    """slug로 등록된 디자인 시안을 찾는다. 없으면 None을 반환한다."""
    for page in _DESIGN_PAGES:
        if page.slug == slug:
            return page
    return None


def list_design_pages() -> tuple[DesignPage, ...]:
    """등록된 디자인 시안 목록을 반환한다."""
    return _DESIGN_PAGES


def _render_index() -> str:
    """등록된 시안을 모두 링크한 목록 페이지 HTML을 만든다."""
    sections = "".join(
        f"""
  <section>
    <h2><a href="/dev/design/{html.escape(page.slug)}">{html.escape(page.title)}</a></h2>
    <p class="description">{html.escape(page.description)}</p>
  </section>"""
        for page in _DESIGN_PAGES
    )
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>디자인 시안</title>
  <style>{_PAGE_STYLE}</style>
</head>
<body>
  <h1>디자인 시안</h1>
  <p class="subtitle">확정안이 아니라 논의용 시안입니다.
  설계 배경은 docs/interest-feedback-ux-design.md를 참고하세요.</p>
{sections}
</body>
</html>"""


@router.get("/design", response_class=HTMLResponse, include_in_schema=False)
async def show_design_index() -> HTMLResponse:
    """등록된 디자인 시안 목록 페이지를 반환한다."""
    return HTMLResponse(_render_index())


@router.get("/design/{slug}", response_class=HTMLResponse, include_in_schema=False)
async def show_design_page(slug: str) -> HTMLResponse:
    """디자인 시안 하나의 HTML을 반환한다."""
    page = get_design_page(slug)
    if page is None:
        raise AgentApiError(
            status.HTTP_404_NOT_FOUND,
            ErrorDetail(code="DESIGN_PAGE_NOT_FOUND", message="등록되지 않은 시안입니다."),
        )
    return HTMLResponse((_TEMPLATE_DIR / page.template).read_text(encoding="utf-8"))
