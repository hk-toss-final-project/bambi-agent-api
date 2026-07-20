"""스코어링(scoring)과 설정(config) 검증. 순수 계산만 하며 네트워크는 호출하지 않는다."""

import importlib
import math
from datetime import UTC, datetime, timedelta

import pytest

from agent.assistant import config, scoring

_NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def test_freshness_news_half_life() -> None:
    """뉴스 타입은 λ=0.5로 감쇠한다 (약 1.4일에 절반)."""
    published = _NOW - timedelta(days=2)
    score = scoring.freshness_score(published, "news", now=_NOW)
    assert score == pytest.approx(math.exp(-config.LAMBDA_NEWS * 2))


def test_freshness_evergreen_decays_slowly() -> None:
    """에버그린 타입은 λ=0.05로 거의 감쇠하지 않는다."""
    published = _NOW - timedelta(days=2)
    news = scoring.freshness_score(published, "news", now=_NOW)
    evergreen = scoring.freshness_score(published, "evergreen", now=_NOW)
    assert evergreen == pytest.approx(math.exp(-config.LAMBDA_EVERGREEN * 2))
    assert evergreen > news


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


def test_config_env_override(monkeypatch) -> None:
    """설정값은 같은 이름의 환경변수로 오버라이드할 수 있다."""
    monkeypatch.setenv("COLLECT_WINDOW_DAYS", "5")
    monkeypatch.setenv("MIN_SIMILARITY", "0.7")
    try:
        importlib.reload(config)
        assert config.COLLECT_WINDOW_DAYS == 5
        assert config.MIN_SIMILARITY == 0.7
        assert config.collect_window_hours() == 120.0
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_config_invalid_env_falls_back_to_default(monkeypatch) -> None:
    """형식이 잘못된 환경변수는 무시하고 기본값을 쓴다."""
    monkeypatch.setenv("COLLECT_WINDOW_DAYS", "사흘")
    try:
        importlib.reload(config)
        assert config.COLLECT_WINDOW_DAYS == 3
    finally:
        monkeypatch.undo()
        importlib.reload(config)
