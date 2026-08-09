"""개인 Wiki Graph 시각화 페이지 라우터."""

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from app.wiki_graph.page import render_wiki_graph_page

router = APIRouter()


@router.get("/wiki-graph", response_class=HTMLResponse, include_in_schema=False)
async def wiki_graph_page(
    request: Request,
    user_id: Annotated[
        str | None,
        Query(min_length=1, max_length=128, description="그래프로 조회할 사용자 ID"),
    ] = None,
) -> str:
    """Obsidian 스타일 개인 Wiki 관계 Graph 페이지를 반환한다."""
    settings = request.app.state.container.settings
    return render_wiki_graph_page(settings.api_prefix, user_id or "")
