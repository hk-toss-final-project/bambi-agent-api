"""FastAPI MVP 시스템 및 내부 API 라우터 조립 기능."""

from fastapi import APIRouter

from app.routers.service.routes import router as service_router
from app.routers.service_worker.routes import router as service_worker_router
from app.routers.system import router as system_router
from app.routers.wiki_graph import router as wiki_graph_router


def build_api_router(api_prefix: str) -> APIRouter:
    """시스템 API와 Service·Worker 내부 API를 하나의 Router로 조립한다."""
    router = APIRouter()
    router.include_router(system_router)
    router.include_router(wiki_graph_router)
    router.include_router(service_router, prefix=api_prefix)
    router.include_router(service_worker_router, prefix=api_prefix)
    return router
