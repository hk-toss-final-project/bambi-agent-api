"""스코어링(scoring)과 설정(config) 검증. 순수 계산만 하며 네트워크는 호출하지 않는다."""

import importlib
import math
from datetime import UTC, datetime, timedelta

import pytest

from agent.selection.features import config, scoring

_NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def test_freshness_news_half_life() -> None:
    """뉴스 타입은 λ=0.5로 감쇠한다 (약 1.4일에 절반)."""
    published = _NOW - timedelta(days=2)
    score = scoring.freshness_score(published, "news", now=_NOW)
    assert score == pytest.approx(math.exp(-config.LAMBDA_NEWS * 2))


def test_freshness_evergreen_decays_slowly() -> None:
    """에버그린 타입은 뉴스보다 훨씬 느리게 감쇠한다."""
    published = _NOW - timedelta(days=2)
    news = scoring.freshness_score(published, "news", now=_NOW)
    evergreen = scoring.freshness_score(published, "evergreen", now=_NOW)
    assert evergreen == pytest.approx(math.exp(-config.LAMBDA_EVERGREEN * 2))
    assert evergreen > news


def test_freshness_evergreen_survives_months() -> None:
    """개념 문서는 몇 달이 지나도 발행 후보로 남을 만큼 신선도를 유지한다.

    이전 λ=0.05(반감기 약 14일)에서는 개념형 키워드의 실시간 자료가 통째로
    탈락했다(2026-07-27 'DDD' 리포트 실측 0건). 공식을 되뇌는 대신 "얼마나
    오래 살아남아야 하는가"를 못박아, 값이 뉴스 쪽으로 되돌아가면 실패시킨다.
    """
    half_year = scoring.freshness_score(_NOW - timedelta(days=180), "evergreen", now=_NOW)
    one_year = scoring.freshness_score(_NOW - timedelta(days=365), "evergreen", now=_NOW)

    # 반년 전 개념 글이 최신 대비 절반 이상의 신선도를 유지해야 한다.
    assert half_year > 0.5
    # 1년 전 글도 완전히 죽지 않아야 한다(반감기 ≈ 1년).
    assert one_year > 0.45

    # 같은 시점의 뉴스는 사실상 소멸해 있어야 한다 — 두 타입이 구분되는지 확인.
    assert scoring.freshness_score(_NOW - timedelta(days=180), "news", now=_NOW) < 0.01


def test_freshness_cold_start_is_neutral() -> None:
    """콜드 스타트에서는 발행일이 있어도 신선도를 중립값 0.5로 고정한다."""
    published = _NOW - timedelta(days=30)
    assert scoring.freshness_score(published, "news", now=_NOW, cold_start=True) == config.COLD_START_FRESHNESS


def test_freshness_unknown_date_is_neutral() -> None:
    """발행일 미상(None)이면 중립값을 쓴다."""
    assert scoring.freshness_score(None, "news", now=_NOW) == config.COLD_START_FRESHNESS


def test_source_weight_lookup() -> None:
    """공식/언론/커뮤니티/미등록 소스의 가중치를 도메인으로 찾는다."""
    assert scoring.source_weight("https://openai.com/blog/x") == 1.0
    assert scoring.source_weight("https://www.hankyung.com/article/1") == 0.8
    assert scoring.source_weight("https://www.reddit.com/r/x/1") == 0.6
    assert scoring.source_weight("https://unknown-blog.example/post") == config.DEFAULT_SOURCE_WEIGHT


def test_source_weight_matches_subdomain() -> None:
    """서브도메인(news.hankyung.com)도 등록 도메인 접미사로 매칭한다."""
    assert scoring.source_weight("https://news.hankyung.com/a") == 0.8


def test_cluster_boost_formula_and_cap() -> None:
    """cluster_boost = 1 + 0.1×(크기-1)이며 상한 1.5를 넘지 않는다."""
    assert scoring.cluster_boost(1) == 1.0
    assert scoring.cluster_boost(3) == pytest.approx(1.2)
    assert scoring.cluster_boost(10) == config.CLUSTER_BOOST_CAP


def test_final_score_is_product() -> None:
    """final_score = similarity × freshness × source_weight × cluster_boost."""
    assert scoring.final_score(0.9, 0.5, 0.8, 1.2) == pytest.approx(0.9 * 0.5 * 0.8 * 1.2)


def test_classify_content_type() -> None:
    """제목의 개념/튜토리얼 키워드로 에버그린을 분류하고, 그 외는 뉴스로 본다."""
    assert scoring.classify_content_type({"title": "전고체 배터리 개념 정리 튜토리얼"}) == "evergreen"
    assert scoring.classify_content_type({"title": "Transformer Guide for beginners"}) == "evergreen"
    assert scoring.classify_content_type({"title": "삼성, 신형 배터리 양산 발표"}) == "news"


def test_score_document_combines_components() -> None:
    """score_document가 구성 요소와 final_score를 함께 반환한다."""
    doc = {"title": "새 발표", "url": "https://openai.com/blog/x", "published": _NOW}
    result = scoring.score_document(doc, 0.9, boost=1.1, now=_NOW)

    assert result["content_type"] == "news"
    assert result["similarity"] == 0.9
    assert result["freshness"] == pytest.approx(1.0)
    assert result["source_weight"] == 1.0
    assert result["final_score"] == pytest.approx(0.9 * 1.0 * 1.0 * 1.1)


def test_score_document_prefers_source_url_over_redirect() -> None:
    """뉴스 문서는 Google News 리다이렉트 url이 아니라 원본 발행처로 가중치를 매긴다."""
    doc = {
        "title": "코스피 급락",
        "url": "https://news.google.com/rss/articles/CBMiabc123",
        "source_url": "https://www.chosun.com",
        "published": _NOW,
    }
    result = scoring.score_document(doc, 0.5, now=_NOW)

    # source_url이 없었다면 news.google.com → 미등록 기본값(0.5)을 받았을 것이다.
    assert result["source_weight"] == 0.8


def test_score_document_falls_back_to_url_without_source() -> None:
    """source_url이 없는 문서(YouTube·Reddit)는 기존대로 url로 가중치를 매긴다."""
    doc = {"title": "영상", "url": "https://www.youtube.com/watch?v=x", "published": _NOW}
    assert scoring.score_document(doc, 0.5, now=_NOW)["source_weight"] == 0.6


def test_similarity_cutoff_scales_with_best_match() -> None:
    """유사도 컷은 이번 실행 최고 유사도에 비례해 움직인다."""
    # 유사도가 높게 형성되는 키워드일수록 컷도 함께 올라간다.
    assert config.similarity_cutoff(0.48) == pytest.approx(0.48 * config.SIMILARITY_RATIO)
    assert config.similarity_cutoff(0.40) == pytest.approx(0.40 * config.SIMILARITY_RATIO)
    assert config.similarity_cutoff(0.48) > config.similarity_cutoff(0.40)


def test_similarity_cutoff_never_below_floor() -> None:
    """수집 결과가 통째로 무관하면 절대 하한이 걸린다."""
    # 최고 유사도가 0.1이면 상대 컷은 0.075지만, 하한 아래로는 내려가지 않는다.
    assert config.similarity_cutoff(0.1) == config.SIMILARITY_FLOOR


def test_publish_cutoff_scales_with_best_score() -> None:
    """발행 컷도 이번 실행 최고 점수에 상대적으로 정해진다."""
    assert config.publish_cutoff(0.30) == pytest.approx(0.30 * config.PUBLISH_RATIO)
    assert config.publish_cutoff(0.01) == config.PUBLISH_FLOOR


def test_realistic_news_score_passes_publish_cutoff() -> None:
    """실측 수준의 뉴스 문서가 발행 컷을 통과한다 (회귀 방지).

    수정 전에는 유사도 0.6·점수 0.5라는 고정 임계값이 실제 분포(유사도 최대
    0.475, 점수 최대 0.357)보다 높아 어떤 문서도 통과할 수 없었다.
    """
    doc = {
        "title": "코스피 급락",
        "url": "https://news.google.com/rss/articles/CBMiabc123",
        "source_url": "https://www.chosun.com",
        "published": _NOW - timedelta(hours=6),
    }
    score = scoring.score_document(doc, 0.45, now=_NOW)["final_score"]

    assert score >= config.publish_cutoff(score)


def test_config_env_override(monkeypatch) -> None:
    """선별 임계값은 같은 이름의 환경변수로 오버라이드할 수 있다."""
    monkeypatch.setenv("SIMILARITY_FLOOR", "0.7")
    monkeypatch.setenv("MAX_DAILY_ITEMS", "9")
    try:
        importlib.reload(config)
        assert config.SIMILARITY_FLOOR == 0.7
        assert config.MAX_DAILY_ITEMS == 9
        # 컷 계산 함수도 오버라이드된 값을 따라야 한다.
        assert config.similarity_cutoff(0.1) == 0.7
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_config_invalid_env_falls_back_to_default(monkeypatch) -> None:
    """형식이 잘못된 환경변수는 무시하고 기본값을 쓴다."""
    monkeypatch.setenv("MAX_DAILY_ITEMS", "다섯")
    monkeypatch.setenv("SIMILARITY_RATIO", "많이")
    try:
        importlib.reload(config)
        assert config.MAX_DAILY_ITEMS == 5
        assert config.SIMILARITY_RATIO == 0.75
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_topic_intent_overrides_title_heuristic() -> None:
    """토픽 성격이 주어지면 제목 휴리스틱보다 우선한다.

    제목 정규식은 실측에서 취약했다 — 'DDD의 재발견'처럼 개념 글인데 '튜토리얼·
    입문·가이드' 같은 단어가 없으면 news로 오분류된다. 개인 Wiki가 concept으로
    분류한 토픽이면 그 판단을 따라야 수집 창을 넓힌 효과가 살아난다.
    """
    doc = {"title": "DDD의 재발견 - 브런치"}

    # 성격 미지정: 기존 휴리스틱대로 news (제목에 개념 키워드가 없다)
    assert scoring.classify_content_type(doc) == "news"
    # 성격 지정: Wiki 판단을 따른다
    assert scoring.classify_content_type(doc, topic_intent="evergreen") == "evergreen"
    assert scoring.classify_content_type(doc, topic_intent="news") == "news"


def test_score_document_uses_topic_intent_for_decay() -> None:
    """토픽이 개념형이면 오래된 문서도 신선도를 유지해 점수가 살아남는다.

    창을 넓혀도 문서가 news로 분류되면 λ=0.5로 깎여 결국 탈락한다. 창과 감쇠가
    같은 판정을 따라야 개념형 토픽에서 실시간 자료가 0건이 되지 않는다.
    """
    old_doc = {"title": "DDD의 재발견 - 브런치", "published": _NOW - timedelta(days=60)}

    without_intent = scoring.score_document(old_doc, 0.5, now=_NOW)
    with_intent = scoring.score_document(old_doc, 0.5, now=_NOW, topic_intent="evergreen")

    assert without_intent["content_type"] == "news"
    assert with_intent["content_type"] == "evergreen"
    # 60일 지난 문서: 뉴스 기준이면 사실상 소멸, 개념 기준이면 대부분 유지된다.
    assert without_intent["freshness"] < 0.01
    assert with_intent["freshness"] > 0.85
    assert with_intent["final_score"] > without_intent["final_score"] * 50
