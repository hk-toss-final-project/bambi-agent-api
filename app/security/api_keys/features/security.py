"""MCP Personal Access Token의 생성과 Hash 기능."""

import hashlib
import secrets
from dataclasses import dataclass


MCP_API_KEY_PREFIX = "bmb_mcp"


@dataclass(frozen=True, slots=True)
class GeneratedApiKey:
    """발급 시 한 번만 노출할 원문 Key와 저장용 식별 정보를 담는다."""

    raw_key: str
    key_prefix: str
    key_hash: str


async def key_008(raw_key: str | None = None) -> GeneratedApiKey:
    """[KEY-008] API Key Hash 저장.

    원문 Key를 새로 만들거나 전달받아 식별 Prefix와 SHA-256 Hash를 반환한다.
    원문은 호출자에게만 반환하고 저장소에는 Prefix와 Hash만 전달한다.
    """
    if raw_key is None:
        key_prefix = f"{MCP_API_KEY_PREFIX}_{secrets.token_hex(6)}"
        raw_key = f"{key_prefix}.{secrets.token_urlsafe(32)}"
    else:
        key_prefix = parse_api_key_prefix(raw_key)
    return GeneratedApiKey(
        raw_key=raw_key,
        key_prefix=key_prefix,
        key_hash=hashlib.sha256(raw_key.encode("utf-8")).hexdigest(),
    )


def parse_api_key_prefix(raw_key: str) -> str:
    """원문 Key에서 DB 조회에 사용할 공개 식별 Prefix를 추출한다."""
    prefix, separator, secret = raw_key.partition(".")
    if (
        not separator
        or not secret
        or not prefix.startswith(f"{MCP_API_KEY_PREFIX}_")
        or len(prefix) != len(MCP_API_KEY_PREFIX) + 1 + 12
    ):
        raise ValueError("MCP API Key 형식이 올바르지 않습니다.")
    return prefix
