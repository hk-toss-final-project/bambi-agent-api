"""Global Source 처리 단계의 정규화·중복 제거·Namespace 보호를 검증한다."""

import asyncio

import pytest

from infrastructure.sources.connectors.api import LatestArticle
from infrastructure.sources.processing.features.deduplication import gsp_006
from infrastructure.sources.processing.features.normalization import gsp_004
from infrastructure.sources.processing.features.safeguards import gsp_015


def test_gsp_004_normalizes_fields_and_drops_blank_urls() -> None:
    """기사 필드의 공백을 제거하고 URL 없는 항목은 제외한다."""
    articles = [
        LatestArticle(
            provider=" naver ",
            title=" 제목 ",
            url=" https://example.com/article ",
            description=" 설명 ",
            source_name="  ",
            language=" ko ",
        ),
        LatestArticle(
            provider="newsapi",
            title="제외",
            url="  ",
            description="URL 없음",
        ),
    ]

    result = asyncio.run(gsp_004(articles))

    assert result == [
        LatestArticle(
            provider="naver",
            title="제목",
            url="https://example.com/article",
            description="설명",
            source_name=None,
            language="ko",
        )
    ]


def test_gsp_006_keeps_first_article_for_each_normalized_url() -> None:
    """대소문자와 주변 공백이 다른 동일 URL에서 첫 기사만 유지한다."""
    first = LatestArticle("naver", "첫 기사", "https://EXAMPLE.com/a", "설명")
    duplicate = LatestArticle(
        "newsapi", "중복 기사", " https://example.COM/a ", "설명"
    )

    assert asyncio.run(gsp_006([first, duplicate])) == [first]


def test_gsp_015_rejects_non_global_namespace() -> None:
    """수집 문서를 개인 Namespace로 저장하려는 시도를 거부한다."""
    asyncio.run(gsp_015("global"))

    with pytest.raises(ValueError, match="Global Namespace"):
        asyncio.run(gsp_015("user/user-1"))
