"""Obsidian 스타일 개인 Wiki Graph HTML 페이지 렌더링.

HTML·CSS·JS 본문은 templates/graph.html 템플릿 파일이 소유하고, 파이썬은
템플릿 로드와 사용자 입력 이스케이프 치환만 담당한다. 지식 데이터는
PWIKI-003 API에서만 읽는다.
"""

import html
import json
from pathlib import Path

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "graph.html"
_PAGE_TEMPLATE = _TEMPLATE_PATH.read_text(encoding="utf-8")


def render_wiki_graph_page(api_prefix: str, initial_user_id: str) -> str:
    """API Prefix와 초기 사용자 ID를 주입한 Wiki Graph HTML을 반환한다."""
    return _PAGE_TEMPLATE.replace(
        "__API_PREFIX_JSON__", json.dumps(api_prefix)
    ).replace("__INITIAL_USER_ID__", html.escape(initial_user_id, quote=True))
