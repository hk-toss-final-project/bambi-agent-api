"""발행일 추출 폴백 체인(dates) 검증. 네트워크는 호출하지 않는다."""

from datetime import UTC, datetime

from agent.assistant import dates


def test_pub_ts_has_top_priority() -> None:
    """RSS pubDate(published_ts)가 있으면 다른 단서보다 우선한다."""
    ts = datetime(2026, 7, 14, 9, 0, tzinfo=UTC).timestamp()
    published, method = dates.extract_published(
        published_ts=ts,
        html='<meta property="article:published_time" content="2020-01-01T00:00:00Z">',
        url="https://a.com/2019/01/old",
    )
    assert method == "pub_date"
    assert published == datetime(2026, 7, 14, 9, 0, tzinfo=UTC)


def test_meta_tag_fallback_when_no_pub_ts() -> None:
    """pubDate가 없으면 article:published_time 메타태그에서 추출한다."""
    html = '<head><meta property="article:published_time" content="2026-07-13T10:30:00+09:00"></head>'
    published, method = dates.extract_published(published_ts=0, html=html, url="")

    assert method == "html_meta"
    assert published == datetime(2026, 7, 13, 1, 30, tzinfo=UTC)  # UTC로 변환됨


def test_meta_tag_reversed_attribute_order() -> None:
    """content가 property보다 앞에 오는 메타태그도 추출한다."""
    html = '<meta content="2026-07-13T00:00:00Z" property="article:published_time">'
    published, method = dates.extract_published(published_ts=0, html=html, url="")

    assert method == "html_meta"
    assert published is not None and published.date().isoformat() == "2026-07-13"


def test_json_ld_date_published() -> None:
    """JSON-LD의 datePublished에서 추출한다."""
    html = '<script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2026-07-12T08:00:00Z"}</script>'
    published, method = dates.extract_published(published_ts=0, html=html, url="")

    assert method == "html_meta"
    assert published is not None and published.date().isoformat() == "2026-07-12"


def test_jina_published_time_header() -> None:
    """Jina Reader 텍스트의 'Published Time:' 헤더에서 추출한다."""
    text = "Title: 기사\nURL Source: https://a.com\nPublished Time: 2026-07-11T02:00:00Z\nMarkdown Content:\n본문"
    published, method = dates.extract_published(published_ts=0, html=text, url="")

    assert method == "html_meta"
    assert published is not None and published.date().isoformat() == "2026-07-11"


def test_url_path_patterns() -> None:
    """URL 경로의 /연/월/일, /연/월, YYYYMMDD 패턴에서 추정한다."""
    full, method_full = dates.extract_published(published_ts=0, html="", url="https://a.com/2026/07/19/article")
    assert (method_full, full.date().isoformat()) == ("url_path", "2026-07-19")

    month_only, _ = dates.extract_published(published_ts=0, html="", url="https://a.com/2026/07/article")
    assert month_only.date().isoformat() == "2026-07-01"  # 일 미상이면 1일

    compact, _ = dates.extract_published(published_ts=0, html="", url="https://a.com/news/20260719-title")
    assert compact.date().isoformat() == "2026-07-19"


def test_body_parse_via_htmldate() -> None:
    """메타태그·URL에서 못 찾으면 htmldate로 본문에서 파싱한다."""
    html = '<html><head><meta name="date" content="2026-07-10"></head><body>본문</body></html>'
    published, method = dates.extract_published(published_ts=0, html=html, url="")

    assert method == "body_parse"
    assert published is not None and published.date().isoformat() == "2026-07-10"


def test_all_failed_returns_none() -> None:
    """전부 실패하면 (None, "none")을 반환한다 — 호출자가 first_seen을 대용으로 쓴다."""
    published, method = dates.extract_published(published_ts=0, html="", url="https://a.com/article")

    assert published is None
    assert method == "none"


def test_rfc2822_date_string_parses() -> None:
    """RFC 2822 형식("Mon, 14 Jul 2026 ...") 날짜 문자열도 파싱한다."""
    parsed = dates._parse_datetime("Mon, 13 Jul 2026 09:00:00 GMT")
    assert parsed == datetime(2026, 7, 13, 9, 0, tzinfo=UTC)
