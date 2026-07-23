"""FastAPI MVP 시스템 및 내부 API 라우터 조립 기능."""

from fastapi import APIRouter

from app.config import Settings
from app.routers.service.routes import router as service_router
from app.routers.service_worker.routes import router as service_worker_router
from app.routers.system import router as system_router
from app.routers.wiki_graph import router as wiki_graph_router


def build_api_router(settings: Settings) -> APIRouter:
    """시스템 API와 Service·Worker 내부 API를 하나의 Router로 조립한다."""
    router = APIRouter()
    router.include_router(system_router)
    router.include_router(wiki_graph_router)
    router.include_router(service_router, prefix=settings.api_prefix)
    router.include_router(service_worker_router, prefix=settings.api_prefix)
    if settings.dev_agent_api_enabled:
        from app.routers.development.graph_views import router as graph_views_router
        from app.routers.development.routes import router as development_router

        router.include_router(
            development_router,
            prefix=f"{settings.api_prefix}/dev",
        )
        # 사람이 브라우저로 여는 시각화 페이지라 내부 API prefix 없이 /dev에 둔다.
        router.include_router(graph_views_router, prefix="/dev")
    return router
