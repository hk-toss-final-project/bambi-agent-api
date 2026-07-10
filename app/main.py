"""Bambi Agent API의 FastAPI 애플리케이션 진입점.

앱 팩토리, 생명주기, 미들웨어와 최상위 라우터 등록 위치를 제공한다.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.routers.routes import (
    admin_router,
    external_router,
    internal_router,
    mcp_router,
    system_router,
)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """[SYS-001, SYS-012] 시작 리소스 초기화와 안전한 종료 경계를 제공한다."""
    # TODO: DB, Queue, Provider 연결과 종료 처리를 구현한다.
    yield


def register_routers(application: FastAPI) -> None:
    """[SYS-002] 기능 영역별 최상위 API 라우터를 애플리케이션에 등록한다."""
    for router in (
        system_router,
        internal_router,
        external_router,
        admin_router,
        mcp_router,
    ):
        application.include_router(router)


def create_app(settings: Settings | None = None) -> FastAPI:
    """[SYS-001] 설정을 받아 FastAPI 애플리케이션 뼈대를 생성한다."""
    resolved_settings = settings or Settings()
    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
    )
    register_routers(application)
    return application


app = create_app()
