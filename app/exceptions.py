"""Agent API 공통 예외 타입과 전역 오류 응답 처리기."""

import logging
from dataclasses import dataclass
from typing import Mapping

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas.common import ErrorResponseSchema

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ErrorDetail:
    """클라이언트에 노출 가능한 공통 오류 정보."""

    code: str
    message: str
    retryable: bool = False
    details: tuple[dict[str, object], ...] = ()


class AgentApiError(RuntimeError):
    """Agent API의 예상 가능한 도메인 오류."""

    def __init__(
        self,
        status_code: int,
        detail: ErrorDetail,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """HTTP 상태와 안전한 오류 상세를 보존한다."""
        super().__init__(detail.message)
        self.status_code = status_code
        self.detail = detail
        self.headers = dict(headers) if headers is not None else None


def _request_id(request: Request) -> str | None:
    """요청 상태에 저장된 Request ID를 안전하게 조회한다."""
    return getattr(request.state, "request_id", None)


async def handle_agent_api_error(request: Request, exc: AgentApiError) -> JSONResponse:
    """예상 가능한 Agent API 오류를 공통 응답으로 변환한다."""
    body = ErrorResponseSchema(
        code=exc.detail.code,
        message=exc.detail.message,
        request_id=_request_id(request),
        retryable=exc.detail.retryable,
        details=list(exc.detail.details),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(mode="json"),
        headers=exc.headers,
    )


async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """FastAPI 요청 검증 오류를 필드별 공통 오류 응답으로 변환한다."""
    details = [
        {
            "location": ".".join(str(part) for part in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()
    ]
    body = ErrorResponseSchema(
        code="REQUEST_VALIDATION_ERROR",
        message="요청 형식이 올바르지 않습니다.",
        request_id=_request_id(request),
        details=details,
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=body.model_dump(mode="json"),
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """예상하지 못한 오류를 내부 정보가 없는 공통 응답으로 변환한다."""
    # 이 핸들러는 추적 미들웨어 바깥(ServerErrorMiddleware)에서 실행돼 contextvar가
    # 이미 해제된 뒤라, request.state의 ID를 직접 실어 로그 상관관계를 유지한다.
    logger.exception(
        "처리되지 않은 Agent API 오류",
        exc_info=exc,
        extra={"request_id": _request_id(request)},
    )
    body = ErrorResponseSchema(
        code="INTERNAL_SERVER_ERROR",
        message="요청 처리 중 오류가 발생했습니다.",
        request_id=_request_id(request),
        retryable=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=body.model_dump(mode="json"),
    )


def register_exception_handlers(application: FastAPI) -> None:
    """[SYS-007] 공통 오류 응답을 만드는 전역 예외 처리기를 등록한다."""
    application.add_exception_handler(AgentApiError, handle_agent_api_error)  # type: ignore[arg-type]
    application.add_exception_handler(RequestValidationError, handle_validation_error)  # type: ignore[arg-type]
    application.add_exception_handler(Exception, handle_unexpected_error)
