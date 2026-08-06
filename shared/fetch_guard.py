"""수집한 본문이 실제 문서인지, 봇 차단 페이지인지 판정한다.

Jina Reader는 HTTP 요청만 보내므로 봇 차단(Cloudflare 등)·로그인 요구·유료
장벽에 걸리면 **차단 안내 페이지를 정상 응답으로** 돌려준다. 그대로 저장하면
그 안내문이 문서로 남고, LLM이 그것을 읽어 엉뚱한 Wiki 노드를 만든다.

실측(2026-08-06): 사용자가 나무위키 URL을 저장했더니 다음 노드가 생성됐다.

    title:   namu.wiki
    summary: 악성 봇으로부터 보호하기 위해 보안 서비스를 사용하는 웹사이트.
    sources: [[sources/just-a-moment_e1dc02|Just a moment...]]

`Just a moment...`는 Cloudflare 차단 페이지 제목이다. 수집도 Wiki 빌드도
"성공"으로 끝나서, 사용자는 저장됐다고 보고 Wiki에는 쓰레기 노드가 남았다.

**실패는 실패로 남겨야 한다.** 이 모듈은 그 판정만 하고, 처리는 호출자가 한다.
"""

from __future__ import annotations

import re

# 차단·인증 안내 페이지의 제목. 소문자로 비교한다.
#
# 제목만 본다 — 본문에 이 문구가 들어간 정상 기사(보안 뉴스 등)를 오탐하지
# 않기 위해서다. 차단 페이지는 제목 자체가 안내문이다.
_BLOCKED_TITLE_PATTERNS = (
    "just a moment",  # Cloudflare
    "attention required",  # Cloudflare
    "access denied",
    "403 forbidden",
    "404 not found",
    "are you a robot",
    "are you human",
    "verify you are human",
    "checking your browser",
    "please enable javascript",
    "enable cookies",
    "security check",
    "captcha",
    "sign in to continue",
    "log in to continue",
    "subscribe to read",
)

# 본문이 이보다 짧으면 문서로 보지 않는다.
#
# 차단 페이지는 대개 안내 한두 문장뿐이다. 반대로 정상 기사는 짧아도 이 정도는
# 넘는다. 값을 더 올리면 짧은 공지·속보를 잃는다.
MIN_CONTENT_CHARS = 200


class FetchBlockedError(RuntimeError):
    """수집 결과가 본문이 아니라 차단·인증 안내 페이지인 경우."""

    def __init__(self, reason: str, *, title: str = "") -> None:
        """차단 사유와 관측된 제목을 담는다."""
        super().__init__(reason)
        self.reason = reason
        self.title = title


def describe_blocked_fetch(title: str | None, markdown: str | None) -> str | None:
    """수집 결과가 본문이 아니면 사유를, 정상이면 None을 반환한다.

    Args:
        title: 수집한 문서 제목
        markdown: 수집한 본문 Markdown

    Returns:
        차단으로 판정한 사유 문자열. 정상이면 None.
    """
    normalized_title = " ".join(str(title or "").split()).casefold()
    for pattern in _BLOCKED_TITLE_PATTERNS:
        if pattern in normalized_title:
            return f"봇 차단·인증 안내 페이지로 보입니다(제목: {title})."

    body = " ".join(str(markdown or "").split())
    if len(body) < MIN_CONTENT_CHARS:
        return (
            f"본문이 {len(body)}자로 최소 {MIN_CONTENT_CHARS}자에 못 미칩니다. "
            "차단되었거나 본문을 찾지 못한 것으로 봅니다."
        )
    return None


def ensure_fetch_is_readable(title: str | None, markdown: str | None) -> None:
    """수집 결과가 본문이 아니면 FetchBlockedError를 낸다."""
    reason = describe_blocked_fetch(title, markdown)
    if reason is not None:
        raise FetchBlockedError(reason, title=str(title or ""))
