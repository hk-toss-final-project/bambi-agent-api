"""Request ID와 Trace ID를 전달하는 요청 추적 미들웨어."""

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestTracingMiddleware(BaseHTTPMiddleware):
    """API 요청마다 추적 식별자를 생성하고 응답까지 전달한다."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """[SYS-008] 요청 추적 컨텍스트를 만들고 다음 처리기로 전달한다."""
        raise NotImplementedError("[SYS-008] 요청 추적 구현이 필요합니다.")
