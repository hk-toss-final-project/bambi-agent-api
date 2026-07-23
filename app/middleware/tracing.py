"""Request ID와 Trace ID를 전달하는 요청 추적 미들웨어."""

import re
from collections.abc import Awaitable, Callable
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.logging_config import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"
TRACE_ID_HEADER = "X-Trace-ID"
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _resolve_identifier(value: str | None) -> str:
    """유효한 외부 추적 ID를 유지하고 그 외에는 안전한 ID를 생성한다."""
    if value and IDENTIFIER_PATTERN.fullmatch(value):
        return value
    return uuid4().hex


class RequestTracingMiddleware(BaseHTTPMiddleware):
    """API 요청마다 추적 식별자를 생성하고 응답까지 전달한다."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """[SYS-008] 요청 추적 컨텍스트를 만들고 다음 처리기로 전달한다."""
        request_id = _resolve_identifier(request.headers.get(REQUEST_ID_HEADER))
        trace_id = _resolve_identifier(request.headers.get(TRACE_ID_HEADER))
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        # 요청 처리 중 발생하는 모든 로그 레코드에 request_id가 실리도록 한다.
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[TRACE_ID_HEADER] = trace_id
        return response
