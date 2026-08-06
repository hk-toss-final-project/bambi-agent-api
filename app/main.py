"""Report Builder Agent API의 FastAPI 애플리케이션 진입점.

앱 팩토리, 생명주기, 미들웨어와 최상위 라우터 등록 위치를 제공한다.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.config import Settings, load_settings
from app.dependencies import AppContainer, create_container
from app.exceptions import register_exception_handlers
from app.logging_config import configure_logging
from app.middleware.tracing import RequestTracingMiddleware
from app.openapi import (
    OPENAPI_DESCRIPTION,
    SWAGGER_UI_PARAMETERS,
    build_openapi_tags,
    register_swagger_ui,
)
from app.routers.routes import build_api_router


def selector_event_loop() -> asyncio.AbstractEventLoop:
    """psycopg 비동기 Pool과 호환되는 Selector 이벤트 루프를 만든다.

    Windows의 uvicorn 기본 루프는 ProactorEventLoop인데 psycopg 비동기 연결이
    이를 지원하지 않아, DB Pool이 붙지 못하고 DB가 필요한 모든 요청이
    SERVICE_NOT_READY로 실패한다. uvicorn `--loop`에 이 팩토리를 지정하면
    (`--loop app.main:selector_event_loop`) 플랫폼과 무관하게 같은 루프를 쓴다.

    Selector 루프는 Linux·macOS의 기본 구현이기도 해서 그쪽 동작은 바뀌지 않는다.
    `workers/main.py`와 `scripts/*.py`가 쓰는 루프 설정과 같은 이유·같은 선택이다.
    """
    return asyncio.SelectorEventLoop()


async def _start_collection_scheduler(
    application: FastAPI, settings: Settings
) -> asyncio.Task[None] | None:
    """수집 Scheduler를 백그라운드 Task로 띄운다.

    Global 풀을 채우는 정기 수집(SCH-002·003·004)이 서버 기동만으로 돌게 한다.
    수집 주기·키워드는 `agent.global_sources` row가 소유하므로, Service는 스케줄
    관리 API로 그 값을 바꿔 주기를 조정한다.

    **시계는 한 벌만 돌아야 한다.** API를 여러 인스턴스로 띄우면 같은 수집이
    인스턴스 수만큼 중복 실행되므로, 그런 배포에서는
    `ENABLE_COLLECTION_SCHEDULER=false`로 끄고 CLI Scheduler를 한 벌만 띄운다.

    Returns:
        기동한 Scheduler Task. 비활성이거나 DB가 없으면 None
    """
    if not settings.enable_collection_scheduler or not settings.agent_database_url:
        return None
    # 지연 import: Scheduler를 끄면 croniter 등 관련 의존성을 로드하지 않는다.
    from scheduler.api import build_scheduler, run_collection_scheduler_loop

    scheduler = build_scheduler(settings)
    return asyncio.create_task(
        run_collection_scheduler_loop(scheduler),
        name="collection-scheduler",
    )


async def _stop_collection_scheduler(task: asyncio.Task[None] | None) -> None:
    """수집 Scheduler Task를 취소하고 종료를 기다린다."""
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """[SYS-001, SYS-012] 시작 리소스 초기화와 안전한 종료 경계를 제공한다."""
    container: AppContainer = application.state.container
    await container.startup()
    scheduler_task = await _start_collection_scheduler(
        application, container.settings
    )
    application.state.collection_scheduler_task = scheduler_task
    try:
        async with application.state.mcp_server.session_manager.run():
            yield
    finally:
        await _stop_collection_scheduler(scheduler_task)
        application.state.collection_scheduler_task = None
        await container.shutdown()


def register_routers(application: FastAPI, settings: Settings) -> None:
    """[SYS-002] 기능 영역별 최상위 API 라우터를 애플리케이션에 등록한다.

    API 라우터(`/internal/v1` 등)와 함께, 키워드 비서 웹 UI를 같은 프로세스에
    등록한다. 두 실행 경로가 같은 수집·선별 코드를 쓰도록 통합하는 과정에서 서버
    프로세스도 하나로 합쳤다.

    비서 UI는 루트가 아니라 `/assistant` 하위에만 노출한다. 이 저장소는 API
    서버이므로 루트 경로를 사람이 보는 화면이 차지하면 안 되기 때문이다.
    UI가 필요 없는 배포에서는 `ENABLE_ASSISTANT_UI=false`로 끌 수 있다.
    """
    application.include_router(build_api_router(settings))
    if settings.enable_assistant_ui:
        # 지연 import: UI를 끄면 비서 의존성(feedparser 등)을 로드하지 않는다.
        from app.assistant.web import assistant_router

        application.include_router(
            assistant_router,
            include_in_schema=False
        )


def create_app(
    settings: Settings | None = None,
    container: AppContainer | None = None,
) -> FastAPI:
    """[SYS-001] 설정을 받아 FastAPI 애플리케이션 뼈대를 생성한다."""
    resolved_settings = settings or load_settings()
    configure_logging(
        log_level=resolved_settings.log_level,
        log_directory=resolved_settings.log_directory,
    )
    application = FastAPI(
        title=resolved_settings.app_name,
        description=OPENAPI_DESCRIPTION,
        version=resolved_settings.app_version,
        lifespan=lifespan,
        docs_url=None,
        redoc_url="/redoc" if resolved_settings.docs_enabled else None,
        openapi_url="/openapi.json" if resolved_settings.docs_enabled else None,
        openapi_tags=build_openapi_tags(
            include_development=resolved_settings.dev_agent_api_enabled
        ),
        swagger_ui_parameters=SWAGGER_UI_PARAMETERS,
    )
    application.state.container = container or create_container(resolved_settings)
    from mcp_server.main import build_mcp_http_app, build_mcp_server

    mcp_server = build_mcp_server(resolved_settings, application.state.container)
    mcp_http_app = build_mcp_http_app(mcp_server, resolved_settings)
    application.state.mcp_server = mcp_server
    application.add_middleware(RequestTracingMiddleware)
    register_exception_handlers(application)
    register_routers(application, resolved_settings)
    if resolved_settings.docs_enabled:
        register_swagger_ui(application)
    # 기존 FastAPI 경로를 먼저 평가하고 나머지를 MCP ASGI 앱으로 전달한다.
    # MCP 앱 내부 경로가 /mcp이므로 공개 Endpoint도 정확히 /mcp이다.
    application.mount("/", mcp_http_app, name="mcp")
    return application


app = create_app()
