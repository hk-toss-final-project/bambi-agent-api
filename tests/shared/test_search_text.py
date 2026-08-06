"""검색 색인용 본문 정제를 검증한다.

원문(markdown)은 리포트 인용에 쓰고, 검색 색인은 기사 본문만 본다. 이 경계가
깨지면 관련기사 목록에 낀 단어로 무관한 문서가 검색에 걸린다.
"""

from shared.search_text import SEARCH_BODY_MAX_CHARS, build_search_body


def test_menu_before_the_article_is_dropped() -> None:
    """제목을 찾아 그 앞의 사이트 메뉴를 버린다.

    실측(2026-08-05): 본문 시작 전 메뉴가 문서당 평균 6,255자였고, 한 문서는
    24,169자였다. 앞에서부터 자르면 본문에 닿기 전에 잘린다.
    """
    menu = "[정치] [경제] [사회] [스포츠] 블록체인 규제 강화 " * 40
    article = "반도체 수출이 증가세를 이어갔다. " * 20
    body = build_search_body(menu + "반도체 수출 1조달러 전망\n" + article, title="반도체 수출 1조달러 전망")

    assert body is not None
    assert "반도체 수출이 증가세" in body
    # 메뉴에만 있던 단어는 색인 대상에서 빠진다.
    assert "블록체인" not in body


def test_body_is_capped_so_trailing_related_articles_do_not_leak() -> None:
    """상한을 넘는 뒷부분은 버린다. 기사 끝에 관련기사 목록이 붙기 때문이다."""
    article = "코스피가 상승 출발했다. " * 2000
    tail = "[관련기사] 프로야구 개막 / 커피 원두 시세"
    body = build_search_body("코스피 상승 출발\n" + article + tail, title="코스피 상승 출발")

    assert body is not None
    assert len(body) <= SEARCH_BODY_MAX_CHARS
    assert "프로야구" not in body


def test_missing_or_blank_markdown_returns_none() -> None:
    """원문이 없으면 None을 준다. 호출자가 원문으로 대체하도록 둔다."""
    assert build_search_body(None) is None
    assert build_search_body("") is None
    assert build_search_body("   ") is None
