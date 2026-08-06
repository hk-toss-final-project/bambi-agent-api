"""검색어 확장(expand_topic_queries) 단위 테스트.

LLM·DB를 부르지 않는 결정적 함수이므로 mock 없이 그대로 검증한다.
"""

from __future__ import annotations

import pytest

from domain.interests.features.expansion import (
    REASON_DISABLED,
    REASON_EXPANDED,
    REASON_NO_NEIGHBORS,
    expand_topic_queries,
)


def test_원_토픽이_항상_첫_검색어다() -> None:
    result = expand_topic_queries("코스피", related_keywords=["코스닥시장"])

    assert result.queries[0] == "코스피"


def test_wiki_이웃을_보조_검색어로_붙인다() -> None:
    result = expand_topic_queries("코스피", related_keywords=["코스닥시장", "지수선물"])

    assert result.expanded == ("코스닥시장", "지수선물")
    assert result.queries == ("코스피", "코스닥시장", "지수선물")
    assert result.reason == REASON_EXPANDED


def test_상한이_확장_개수를_제한한다() -> None:
    # 수집 시간이 검색어 수에 비례하므로 상한을 넘겨선 안 된다.
    result = expand_topic_queries(
        "코스피", related_keywords=["이웃1", "이웃2", "이웃3"], limit=2
    )

    assert result.expanded == ("이웃1", "이웃2")


def test_상한이_0이면_확장하지_않는다() -> None:
    result = expand_topic_queries("코스피", related_keywords=["코스닥시장"], limit=0)

    assert result.queries == ("코스피",)
    assert result.expanded == ()
    assert result.reason == REASON_DISABLED


def test_이웃이_없으면_원_검색어만_남긴다() -> None:
    """고립 노드 토픽은 기존과 똑같이 검색어 하나로 동작한다."""
    result = expand_topic_queries("코스피")

    assert result.queries == ("코스피",)
    assert result.reason == REASON_NO_NEIGHBORS


def test_원_토픽과_같은_이웃은_건너뛴다() -> None:
    # 대소문자·공백·하이픈만 다른 표기는 같은 검색을 두 번 하는 셈이다.
    result = expand_topic_queries(
        "DDD 아키텍처", related_keywords=["ddd-아키텍처", "Application Layer"]
    )

    assert result.expanded == ("Application Layer",)


def test_이웃끼리_중복이거나_빈_값이면_거른다() -> None:
    result = expand_topic_queries(
        "코스피", related_keywords=["코스닥시장", "  ", "코스닥시장"], limit=3
    )

    assert result.expanded == ("코스닥시장",)


def test_같은_입력은_항상_같은_결과를_준다() -> None:
    assert expand_topic_queries("코스피", related_keywords=["코스닥시장"]) == (
        expand_topic_queries("코스피", related_keywords=["코스닥시장"])
    )


def test_빈_토픽은_오류다() -> None:
    with pytest.raises(ValueError):
        expand_topic_queries("   ")
