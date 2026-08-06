"""수집 결과가 본문인지 차단 페이지인지 판정하는 규칙을 검증한다.

Jina Reader는 봇 차단에 걸려도 200과 함께 안내 페이지를 돌려준다. 그대로
저장하면 그 안내문이 문서로 남고 LLM이 엉뚱한 Wiki 노드를 만든다.
"""

import pytest

from shared.fetch_guard import (
    FetchBlockedError,
    MIN_CONTENT_CHARS,
    describe_blocked_fetch,
    ensure_fetch_is_readable,
)

_ARTICLE = "정부가 반도체 클러스터 기반시설 구축비를 최대 100%까지 지원한다. " * 10


def test_cloudflare_block_page_is_detected() -> None:
    """실측 사례를 그대로 잡는다.

    2026-08-06: 나무위키 URL이 "Just a moment..." 페이지를 본문으로 저장해
    "namu.wiki — 악성 봇으로부터 보호하기 위해…" Wiki 노드를 만들었다.
    """
    reason = describe_blocked_fetch("Just a moment...", "잠시만 기다려 주세요." * 40)

    assert reason is not None
    assert "차단" in reason


@pytest.mark.parametrize(
    "title",
    [
        "Attention Required! | Cloudflare",
        "Access denied",
        "403 Forbidden",
        "Checking your browser before accessing",
        "Sign in to continue",
    ],
)
def test_other_block_and_auth_pages_are_detected(title: str) -> None:
    """차단·인증 안내 페이지 제목을 함께 걸러낸다."""
    assert describe_blocked_fetch(title, "안내 문구입니다. " * 40) is not None


def test_short_body_is_treated_as_blocked() -> None:
    """본문이 너무 짧으면 차단이나 추출 실패로 본다."""
    reason = describe_blocked_fetch("정상 제목", "짧은 본문")

    assert reason is not None
    assert str(MIN_CONTENT_CHARS) in reason


def test_normal_article_passes() -> None:
    """정상 기사는 통과시킨다."""
    assert describe_blocked_fetch("반도체 클러스터 지원 확대", _ARTICLE) is None


def test_security_article_is_not_a_false_positive() -> None:
    """본문에 차단 문구가 들어간 보안 기사를 오탐하지 않는다.

    제목만 보는 이유가 이것이다. 본문까지 검사하면 CAPTCHA·봇 차단을 다루는
    정상 기사가 걸린다.
    """
    body = "이 서비스는 captcha와 봇 차단으로 access denied 응답을 준다. " * 10

    assert describe_blocked_fetch("봇 차단 기술의 현재", body) is None


def test_ensure_raises_with_the_reason() -> None:
    """예외 경로는 사유와 제목을 함께 담는다. Job 실패 기록에 쓰인다."""
    with pytest.raises(FetchBlockedError) as caught:
        ensure_fetch_is_readable("Just a moment...", "짧음")

    assert caught.value.title == "Just a moment..."
    assert caught.value.reason
