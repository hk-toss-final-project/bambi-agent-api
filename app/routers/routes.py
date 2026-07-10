"""내부·외부·관리자·MCP API 라우터의 최상위 경계.

상세 URL과 요청/응답 필드는 별도 명세가 확정될 때 하위 라우터에 등록한다.
"""

from fastapi import APIRouter

system_router = APIRouter(prefix="/system", tags=["system"])
internal_router = APIRouter(prefix="/internal", tags=["internal"])
external_router = APIRouter(prefix="/external", tags=["external"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])
mcp_router = APIRouter(prefix="/mcp", tags=["mcp"])
