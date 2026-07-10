"""Bambi Agent API의 FastAPI 애플리케이션 진입점.

앱 팩토리, 생명주기, 미들웨어와 최상위 라우터 등록 위치를 제공한다.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings, load_settings
from app.dependencies import AppContainer, create_container
from app.exceptions import register_exception_handlers
from app.middleware.tracing import RequestTracingMiddleware
from app.routers.routes import build_api_router


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """[SYS-001, SYS-012] 시작 리소스 초기화와 안전한 종료 경계를 제공한다."""
    container: AppContainer = application.state.container
    await container.startup()
    try:
        yield
    finally:
        await container.shutdown()


def register_routers(application: FastAPI, settings: Settings) -> None:
    """[SYS-002] 기능 영역별 최상위 API 라우터를 애플리케이션에 등록한다."""
    application.include_router(build_api_router(settings.api_prefix))


def create_app(
    settings: Settings | None = None,
    container: AppContainer | None = None,
) -> FastAPI:
    """[SYS-001] 설정을 받아 FastAPI 애플리케이션 뼈대를 생성한다."""
    resolved_settings = settings or load_settings()
    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
        docs_url="/docs" if resolved_settings.docs_enabled else None,
        redoc_url="/redoc" if resolved_settings.docs_enabled else None,
        openapi_url="/openapi.json" if resolved_settings.docs_enabled else None,
    )
    application.state.container = container or create_container(resolved_settings)
    application.add_middleware(RequestTracingMiddleware)
    register_exception_handlers(application)
    register_routers(application, resolved_settings)
    return application


app = create_app()
