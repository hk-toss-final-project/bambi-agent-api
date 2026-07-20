"""일간 파이프라인(pipeline) 검증. 네트워크·LLM·임베딩은 모두 대체한다.

수집기는 준비된 문서로, 임베딩은 텍스트→벡터 고정 매핑으로, 통합 요약은
고정 문자열로 대체해 유사도 필터 → 클러스터링 → 스코어링 → 중복 검사 →
임계값 + 워터폴 분기를 결정적으로 검증한다.
"""

from datetime import UTC, datetime, timedelta

import pytest

from agent.assistant import dedup, history, pipeline

_NOW = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)

_TOPIC = "전고체"
_TEXT_A1 = "전고체 배터리 양산 계획 공식 발표 상세"
_TEXT_A2 = "전고체 배터리 양산 발표를 다룬 후속 보도"
_TEXT_B = "전고체 관련 학회 발표 소식 정리"
_TEXT_C = "무관한 게임 신작 출시 소식 안내"

# 토픽 [1,0] 기준: A류 cos≈0.994(동일 이슈 클러스터), B cos≈0.707(별도 클러스터),
# C cos≈0.110(유사도 미달 제외).
_VECTORS = {
    _TOPIC: [1.0, 0.0],
    _TEXT_A1: [0.9, 0.1],
    _TEXT_A2: [0.9, 0.1],
    _TEXT_B: [0.5, 0.5],
    _TEXT_C: [0.1, 0.9],
}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """이력 파일을 임시 디렉터리로 격리하고 임베딩·통합 요약을 대체한다."""
    monkeypatch.setattr(history, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(history, "_COLLECT_HISTORY_PATH", tmp_path / "collect_history.json")
    monkeypatch.setattr(dedup, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(dedup, "_REPORT_EMBEDDING_PATH", tmp_path / "report_embedding_history.json")
    monkeypatch.setattr(pipeline, "embed_texts", lambda texts, model=None: [_VECTORS[t] for t in texts])
    monkeypatch.setattr(pipeline, "complete", lambda s, u, model="gpt-4.1-mini": "통합 인사이트")


def _make_docs() -> list[dict[str, object]]:
    """파이프라인에 넣을 문서 4건(동일 이슈 2건 + 별도 이슈 1건 + 무관 1건)을 만든다."""
    ts = _NOW.timestamp()
    return [
        {"source_type": "news", "title": "전고체 양산 발표", "url": "https://www.hankyung.com/2026/07/a1",
         "url_key": "https://www.hankyung.com/2026/07/a1", "text": _TEXT_A1, "published_ts": ts},
        {"source_type": "news", "title": "전고체 양산 후속 보도", "url": "https://www.etnews.com/a2",
         "url_key": "https://www.etnews.com/a2", "text": _TEXT_A2, "published_ts": ts},
        {"source_type": "news", "title": "전고체 학회 소식", "url": "https://openai.com/blog/b",
         "url_key": "https://openai.com/blog/b", "text": _TEXT_B, "published_ts": ts},
        {"source_type": "reddit", "title": "게임 신작", "url": "https://www.reddit.com/r/g/c",
         "url_key": "https://www.reddit.com/r/g/c", "text": _TEXT_C, "published_ts": ts},
    ]


def _patch_collect(monkeypatch, docs_factory) -> None:
    """수집기를 준비된 문서 팩토리로 대체한다 (호출마다 새 딕셔너리)."""
    monkeypatch.setattr(
        pipeline, "collect_documents", lambda kw, *, now, window_hours: (docs_factory(), [])
    )


def _seed_collect_history() -> None:
    """콜드 스타트가 아니게 만들 시드 수집 이력을 넣는다."""
    history.record_collected(
        "minji", _TOPIC, "https://seed.com/0", "시드", "https://seed.com/0",
        first_seen=_NOW - timedelta(days=2),
    )


def test_daily_mode_selects_clusters_above_threshold(monkeypatch) -> None:
    """유사도 필터 → 클러스터링 → 스코어링을 거쳐 임계값 이상 클러스터를 선정한다."""
    _seed_collect_history()
    _patch_collect(monkeypatch, _make_docs)

    result = pipeline.run_daily(_TOPIC, "minji", reference_now=_NOW)

    assert result["mode"] == "daily"
    assert result["cold_start"] is False
    titles = [item["title"] for item in result["items"]]
    assert titles == ["전고체 양산 발표", "전고체 학회 소식"]  # 점수 내림차순

    top = result["items"][0]
    assert top["cluster_size"] == 2                      # 동일 이슈 2건이 한 클러스터
    assert len(top["sources"]) == 2                      # 출처 링크는 클러스터 전체
    assert top["summary"] == "통합 인사이트"              # 개별 요약이 아닌 통합 요약
    assert top["status"] == "신규"
    assert top["score"] == pytest.approx(0.9939 * 1.0 * 0.8 * 1.1, abs=1e-3)
    assert top["published"].startswith("2026-07-20")

    # 유사도 미달 문서는 사유와 함께 로그에 남는다.
    reasons = [(e["stage"], e["reason"]) for e in result["log"]["exclusions"]]
    assert any(stage == "similarity_filter" and "low_similarity" in reason for stage, reason in reasons)


def test_duplicate_cluster_is_excluded(monkeypatch) -> None:
    """최근 7일 보고서에 실린 것과 사실상 같은 클러스터는 '이미 다룬 소식'으로 뺀다."""
    _seed_collect_history()
    _patch_collect(monkeypatch, _make_docs)
    dedup.record_report_items(
        "minji", _TOPIC,
        [{"url_key": "https://old.com/1", "title": "어제 보고", "embedding": [0.9, 0.1]}],
        now=_NOW - timedelta(days=1),
    )

    result = pipeline.run_daily(_TOPIC, "minji", reference_now=_NOW)

    assert result["mode"] == "daily"
    assert [item["title"] for item in result["items"]] == ["전고체 학회 소식"]
    assert any(e["stage"] == "dedup" for e in result["log"]["exclusions"])


def test_waterfall_weekly_trend_when_no_daily_items(monkeypatch) -> None:
    """당일 아이템이 없으면 최근 7일 수집분 최고 점수 이슈로 주간 트렌드 폴백한다."""
    history.record_collected("minji", _TOPIC, "https://a.com/1", "이슈1", "https://a.com/1",
                             first_seen=_NOW - timedelta(days=3), score=0.7)
    history.record_collected("minji", _TOPIC, "https://a.com/2", "이슈2", "https://a.com/2",
                             first_seen=_NOW - timedelta(days=1), score=0.9)
    history.record_collected("minji", _TOPIC, "https://a.com/old", "옛 이슈", "https://a.com/old",
                             first_seen=_NOW - timedelta(days=20), score=0.95)
    _patch_collect(monkeypatch, lambda: [])

    result = pipeline.run_daily(_TOPIC, "minji", reference_now=_NOW)

    assert result["mode"] == "weekly"
    # 7일 밖 이슈는 제외되고, 점수 내림차순으로 정렬된다.
    assert [item["title"] for item in result["items"]] == ["이슈2", "이슈1"]


def test_waterfall_evergreen_when_nothing_collected(monkeypatch) -> None:
    """수집분도 주간 이력도 없으면 에버그린(개념 정리) 모드로 폴백한다."""
    _patch_collect(monkeypatch, lambda: [])

    result = pipeline.run_daily(_TOPIC, "minji", reference_now=_NOW)

    assert result["mode"] == "evergreen"
    assert result["items"] == []
    assert result["cold_start"] is True


def test_cold_start_uses_neutral_freshness(monkeypatch) -> None:
    """콜드 스타트에서는 신선도를 0.5로 고정해 점수를 계산한다."""
    _patch_collect(monkeypatch, _make_docs)

    result = pipeline.run_daily(_TOPIC, "minji", reference_now=_NOW)

    assert result["cold_start"] is True
    # A1: 0.994 × 0.5(중립) × 0.8 × 1.1 ≈ 0.437 → 임계값 0.5 미달
    recorded = history.get_collected_entries("minji", _TOPIC)
    assert recorded["https://www.hankyung.com/2026/07/a1"]["score"] == pytest.approx(0.437, abs=1e-3)
    assert result["mode"] != "daily"  # 전부 미달이라 당일 모드가 아니다
    assert any(e["stage"] == "threshold" for e in result["log"]["exclusions"])


def test_same_day_rerun_is_idempotent(monkeypatch) -> None:
    """같은 날 재실행해도 같은 아이템이 선정되고 이력이 중복으로 쌓이지 않는다."""
    _seed_collect_history()
    _patch_collect(monkeypatch, _make_docs)

    first = pipeline.run_daily(_TOPIC, "minji", reference_now=_NOW)
    second = pipeline.run_daily(_TOPIC, "minji", reference_now=_NOW + timedelta(hours=2))

    assert [i["title"] for i in first["items"]] == [i["title"] for i in second["items"]]

    # 보고 임베딩 이력은 url_key당 1건만 유지된다.
    data = dedup._load()
    assert len(data["minji"][_TOPIC]) == 2


def test_next_day_skips_already_collected_urls(monkeypatch) -> None:
    """다음 날 같은 URL이 다시 오면 재수집하지 않고 제외한다 (수집 이력 활용)."""
    _seed_collect_history()
    _patch_collect(monkeypatch, _make_docs)
    pipeline.run_daily(_TOPIC, "minji", reference_now=_NOW)

    next_day = pipeline.run_daily(_TOPIC, "minji", reference_now=_NOW + timedelta(days=1))

    reasons = [e["reason"] for e in next_day["log"]["exclusions"]]
    assert reasons.count("url_already_collected") == 4
    # 신규 문서가 없으므로 전날 수집분의 주간 트렌드로 폴백한다.
    assert next_day["mode"] == "weekly"
