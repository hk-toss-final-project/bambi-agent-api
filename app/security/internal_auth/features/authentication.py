"""내부 API Bearer 토큰 인증과 FastAPI 인증 의존성."""

import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import SecretStr

from app.exceptions import AgentApiError, ErrorDetail
from shared.contracts import FeatureRequest, FeatureResult

_INTERNAL_BEARER = HTTPBearer(
    auto_error=False,
    bearerFormat="opaque",
    description="AGENT_INTERNAL_TOKEN으로 설정한 Agent 내부 API Bearer 토큰",
    scheme_name="InternalBearer",
)


@dataclass(frozen=True, slots=True)
class InternalAuthRequest:
    """내부 Bearer 토큰 검증에 필요한 최소 입력."""

    request_id: str
    presented_token: str | None
    configured_token: SecretStr | None


def _authenticate(
    request: InternalAuthRequest,
    *,
    feature_id: str,
    principal: str,
) -> FeatureResult:
    """설정 토큰과 제시된 토큰을 상수 시간으로 비교해 호출 주체를 반환한다."""
    if request.configured_token is None:
        raise AgentApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorDetail(
                code="INTERNAL_AUTH_NOT_CONFIGURED",
                message="내부 API 인증 토큰이 설정되지 않았습니다.",
            ),
        )
    expected = request.configured_token.get_secret_value()
    if request.presented_token is None or not secrets.compare_digest(
        expected, request.presented_token
    ):
        raise AgentApiError(
            status.HTTP_401_UNAUTHORIZED,
            ErrorDetail(
                code="INVALID_INTERNAL_TOKEN",
                message="내부 API 인증 토큰이 올바르지 않습니다.",
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )
    return FeatureResult(feature_id=feature_id, data={"principal": principal})


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def auth_001(request: InternalAuthRequest) -> FeatureResult:
    """[AUTH-001] Service API 인증.

    service-api의 내부 호출 권한을 검증한다.
    """
    return _authenticate(request, feature_id="AUTH-001", principal="service-api")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def auth_002(request: InternalAuthRequest) -> FeatureResult:
    """[AUTH-002] Service Worker 인증.

    service-worker의 내부 호출 권한을 검증한다.
    """
    return _authenticate(request, feature_id="AUTH-002", principal="service-worker")


async def auth_003(request: FeatureRequest) -> FeatureResult:
    """[AUTH-003] Scheduler 인증.

    scheduler의 작업 등록 권한을 검증한다.
    """
    raise NotImplementedError("[AUTH-003] 기능 구현이 필요합니다.")


def _auth_request(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> InternalAuthRequest:
    """FastAPI 요청과 설정에서 기능 계층이 사용할 인증 입력을 만든다."""
    return InternalAuthRequest(
        request_id=request.state.request_id,
        presented_token=credentials.credentials if credentials is not None else None,
        configured_token=request.app.state.container.settings.internal_api_token,
    )


async def require_service_api_access(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(_INTERNAL_BEARER),
    ],
) -> FeatureResult:
    """Service API 및 개발 실행 API 요청의 Bearer 토큰을 검증한다."""
    return await auth_001(_auth_request(request, credentials))


async def require_service_worker_access(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(_INTERNAL_BEARER),
    ],
) -> FeatureResult:
    """Service Worker 요청의 Bearer 토큰을 검증한다."""
    return await auth_002(_auth_request(request, credentials))
