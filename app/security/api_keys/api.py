"""기능 영역의 공개 facade.

구현 모듈의 기능 함수를 안정적인 import 경로로 다시 노출한다.
"""

from .features.authorization import (
    ApiKeyAuthorizationRepository,
    ApiKeyPrincipal,
    key_009,
    key_014,
)
from .features.lifecycle import ALLOWED_API_KEY_SCOPES, ApiKeyLifecycleRepository, IssuedApiKey, key_001, key_002, key_005
from .features.security import GeneratedApiKey, key_008, parse_api_key_prefix

__all__ = [
    "ALLOWED_API_KEY_SCOPES",
    "key_001",
    "key_002",
    "key_005",
    "key_008",
    "key_009",
    "key_014",
    "ApiKeyPrincipal",
    "GeneratedApiKey",
    "IssuedApiKey",
    "parse_api_key_prefix",
    "ApiKeyAuthorizationRepository",
    "ApiKeyLifecycleRepository",
]
