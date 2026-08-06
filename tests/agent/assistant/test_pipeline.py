"""일간 파이프라인(pipeline) 검증. 네트워크·LLM·임베딩은 모두 대체한다.

수집기는 준비된 문서로, 임베딩은 텍스트→벡터 고정 매핑으로, 통합 요약은
고정 문자열로 대체해 유사도 필터 → 클러스터링 → 스코어링 → 중복 검사 →
임계값 + 워터폴 분기를 결정적으로 검증한다.
"""

from datetime import UTC, datetime, timedelta

import pytest

from agent.assistant.features import history, pipeline, storage
from agent.selection.features import dedup

_NOW = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)

_TOPIC = "전고체"
_TEXT_A1 = "전고체 배터리 양산 계획 공식 발표 상세"
_TEXT_A2 = "전고체 배터리 양산 발표를 다룬 후속 보도"
_TEXT_B = "전고체 관련 학회 발표 소식 정리"
_TEXT_C = "무관한 게임 신작 출시 소식 안내"

# 토픽 [1,0,0] 기준 코사인 유사도:
#   A1≈0.46, A2≈0.45 (서로 cos≈1.0 → 동일 이슈 클러스터)
#   B ≈0.40 (A와 cos≈0.18 → 별도 클러스터)
#   C ≈0.11 (유사도 컷 미달 → 제외)
#
# 실제 임베딩(text-embedding-3-small)에서 짧은 키워드와 문서의 유사도는 0.3~0.5
# 좁은 범위에 몰린다. 유사도 컷이 최고값에 상대적이므로, 픽스처도 그 분포를
# 따라야 실제 동작을 검증할 수 있다. 2차원으로는 관련 문서끼리 항상 cos>0.8이
# 되어 클러스터가 분리되지 않으므로 3차원을 쓴다.
_VECTORS = {
    _TOPIC: [1.0, 0.0, 0.0],
    _TEXT_A1: [0.46, 0.888, 0.0],
    _TEXT_A2: [0.45, 0.893, 0.0],
    _TEXT_B: [0.40, 0.0, 0.9165],
    _TEXT_C: [0.11, 0.0, 0.9939],
}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """이력 파일을 임시 디렉터리로 격리하고 임베딩·통합 요약을 대체한다."""
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
        pipeline, "collect_documents", lambda queries, *, now, window_hours: (docs_factory(), [])
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
    assert top["score"] == pytest.approx(0.46 * 1.0 * 0.8 * 1.1, abs=1e-3)
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
        [{"url_key": "https://old.com/1", "title": "어제 보고", "embedding": [0.46, 0.888, 0.0]}],
        history=storage.get_store(),
        now=_NOW - timedelta(days=1),
    )

    result = pipeline.run_daily(_TOPIC, "minji", reference_now=_NOW)

    assert result["mode"] == "daily"
    assert [item["title"] for item in result["items"]] == ["전고체 학회 소식"]
    assert any(e["stage"] == "dedup" for e in result["log"]["exclusions"])


def test_similarity_cutoff_adapts_to_keyword_scale(monkeypatch) -> None:
    """유사도 컷은 고정값이 아니라 이번 실행 최고 유사도에 맞춰 움직인다.

    전체 유사도가 낮게 형성되는 키워드(긴 키워드 등)에서도 상위 문서는 살아남아야
    한다. 고정 임계값이던 때는 이런 키워드가 통째로 탈락했다.
    """
    _seed_collect_history()
    # 유사도가 낮게 형성되는 키워드 상황 (실측: 긴 키워드일수록 최고값이 낮다).
    # 최고 0.35 — 옛 고정 임계값 0.6이었다면 4건 전부 탈락했을 분포다.
    low = {
        _TOPIC: [1.0, 0.0, 0.0],
        _TEXT_A1: [0.35, 0.9367, 0.0],
        _TEXT_A2: [0.34, 0.9404, 0.0],
        _TEXT_B: [0.30, 0.0, 0.9539],
        _TEXT_C: [0.05, 0.0, 0.9987],
    }
    monkeypatch.setattr(pipeline, "embed_texts", lambda texts, model=None: [low[t] for t in texts])
    _patch_collect(monkeypatch, _make_docs)

    result = pipeline.run_daily(_TOPIC, "minji", reference_now=_NOW)

    # 컷이 최고값(0.35)에 맞춰 내려가 상위 문서가 살아남는다.
    assert result["mode"] == "daily"
    assert result["items"]
    assert result["log"]["similarity_cutoff"] < 0.35
    # 무관 문서(0.05)는 여전히 걸러진다 — 컷이 내려가도 하한은 지킨다.
    assert any(e["stage"] == "similarity_filter" for e in result["log"]["exclusions"])


def test_similarity_floor_blocks_wholly_irrelevant_results(monkeypatch) -> None:
    """수집 결과가 통째로 무관하면 절대 하한이 걸려 아무것도 선정하지 않는다.

    상대 컷만 쓰면 "가장 덜 무관한 문서"가 항상 통과해버린다. 하한이 이를 막고,
    이 경우 보고서는 근거 없이 생성되지 않는다.
    """
    _seed_collect_history()
    irrelevant = {
        _TOPIC: [1.0, 0.0, 0.0],
        _TEXT_A1: [0.10, 0.995, 0.0],
        _TEXT_A2: [0.09, 0.996, 0.0],
        _TEXT_B: [0.08, 0.0, 0.997],
        _TEXT_C: [0.05, 0.0, 0.9987],
    }
    monkeypatch.setattr(
        pipeline, "embed_texts", lambda texts, model=None: [irrelevant[t] for t in texts]
    )
    _patch_collect(monkeypatch, _make_docs)

    result = pipeline.run_daily(_TOPIC, "minji", reference_now=_NOW)

    assert result["mode"] != "daily"
    assert result["log"]["after_similarity_filter"] == 0


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
    """콜드 스타트에서는 신선도를 중립값 0.5로 고정해 점수를 계산한다."""
    _patch_collect(monkeypatch, _make_docs)

    result = pipeline.run_daily(_TOPIC, "minji", reference_now=_NOW)

    assert result["cold_start"] is True
    # A1: 0.46 × 0.5(중립) × 0.8 × 1.1 ≈ 0.202
    recorded = history.get_collected_entries("minji", _TOPIC)
    assert recorded["https://www.hankyung.com/2026/07/a1"]["score"] == pytest.approx(0.202, abs=1e-3)


def test_cold_start_still_produces_daily_items(monkeypatch) -> None:
    """콜드 스타트여도 아이템이 선정된다 (회귀 방지).

    발행 컷이 고정값 0.5이던 때는 중립 신선도(0.5)가 곱해지는 콜드 스타트에서
    어떤 문서도 그 값에 닿지 못해, 처음 조회하는 키워드는 항상 0건이 되고
    근거 없는 폴백 경로로 빠졌다. 컷이 상대값이 되면서 해소된 동작이다.
    """
    _patch_collect(monkeypatch, _make_docs)

    result = pipeline.run_daily(_TOPIC, "minji", reference_now=_NOW)

    assert result["cold_start"] is True
    assert result["mode"] == "daily"
    assert result["items"]


def test_same_day_rerun_is_idempotent(monkeypatch) -> None:
    """같은 날 재실행해도 같은 아이템이 선정되고 이력이 중복으로 쌓이지 않는다."""
    _seed_collect_history()
    _patch_collect(monkeypatch, _make_docs)

    first = pipeline.run_daily(_TOPIC, "minji", reference_now=_NOW)
    second = pipeline.run_daily(_TOPIC, "minji", reference_now=_NOW + timedelta(hours=2))

    assert [i["title"] for i in first["items"]] == [i["title"] for i in second["items"]]

    # 보고 임베딩 이력은 url_key당 1건만 유지된다(재실행해도 중복 누적 없음).
    recorded = dedup.load_recent_report_items(
        "minji", _TOPIC, history=storage.get_store(), now=_NOW,
        lookback_days=365, exclude_today=False,
    )
    assert len(recorded) == 2


def test_search_query_drives_collection_but_topic_drives_scoring(monkeypatch) -> None:
    """search_query는 수집에만 쓰고, 이력·유사도 채점은 여전히 토픽(keyword) 기준이다.

    에이전트가 검색어를 재구성해 넘겨도 개인화·중복 방지 축(토픽)은 흔들리지
    않아야 한다.
    """
    _seed_collect_history()
    captured: dict[str, object] = {}

    def spy_collect(queries, *, now, window_hours):
        captured["collect_queries"] = list(queries)
        return _make_docs(), []

    def spy_embed(texts, model=None):
        captured["embed_target"] = texts[0]  # 유사도 기준이 되는 첫 텍스트
        return [_VECTORS[t] for t in texts]

    monkeypatch.setattr(pipeline, "collect_documents", spy_collect)
    monkeypatch.setattr(pipeline, "embed_texts", spy_embed)

    result = pipeline.run_daily(_TOPIC, "minji", reference_now=_NOW, search_query="전고체 배터리 양산")

    assert captured["collect_queries"] == ["전고체 배터리 양산"]  # 수집은 재구성 검색어로
    assert captured["embed_target"] == _TOPIC                 # 채점은 토픽으로
    assert result["log"]["search_query"] == "전고체 배터리 양산"
    # 이력은 토픽(_TOPIC) 키 아래에 기록된다(재구성 검색어 아래가 아님).
    assert history.get_collected_entries("minji", _TOPIC)


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


def test_youtube_documents_use_video_id_as_url_key(monkeypatch) -> None:
    """유튜브 문서의 url_key는 영상별로 고유해야 한다.

    canonical_url은 query를 제거해 모든 watch URL(?v=...)이 같은 key로 뭉개지고,
    기초 필터가 두 번째 영상부터 duplicate_url로, 다음 실행부터는 전체를
    url_already_collected로 오판해 유튜브 결과가 사라지는 회귀를 방지한다.
    """
    monkeypatch.setattr(
        pipeline.youtube,
        "search_videos",
        lambda keyword, limit=4: [
            {"video_id": "vid1", "title": "영상1", "url": "https://www.youtube.com/watch?v=vid1", "published_time": "5 hours ago"},
            {"video_id": "vid2", "title": "영상2", "url": "https://www.youtube.com/watch?v=vid2", "published_time": "10 hours ago"},
        ],
    )

    docs = pipeline._youtube_documents("전고체", _NOW, 72.0)

    keys = [str(doc["url_key"]) for doc in docs]
    assert len(keys) == 2
    assert len(set(keys)) == 2  # 영상마다 고유 key여야 기초 필터를 통과한다
    assert "vid1" in keys[0]
    assert "vid2" in keys[1]


def test_news_documents_reuse_global_body_when_available(monkeypatch) -> None:
    """Global 저장소에 본문이 있으면 스니펫 대신 본문을 텍스트로 쓴다.

    본문이 없는 기사는 기존처럼 Provider 설명 스니펫으로 동작한다(폴백).
    """
    from datetime import UTC, datetime

    entries = [
        {
            "title": "본문 있는 기사",
            "link": "https://n.example/full",
            "summary": "짧은 설명",
            "published": "", "published_ts": 100, "source_url": "", "source_name": "",
        },
        {
            "title": "본문 없는 기사",
            "link": "https://n.example/short",
            "summary": "짧은 설명만 있음",
            "published": "", "published_ts": 90, "source_url": "", "source_name": "",
        },
    ]
    monkeypatch.setattr(
        pipeline.feeds, "fetch_provider_entries", lambda keyword, **kwargs: entries
    )
    monkeypatch.setattr(
        pipeline.content_store,
        "fetch_global_article_texts",
        lambda urls: {"https://n.example/full": "# 제목\n\n저장된 **전체 본문**입니다."},
    )

    docs = pipeline._news_documents("키워드", datetime.now(UTC))

    by_url = {doc["url"]: doc for doc in docs}
    # 마크다운 표기(#, **)는 걷어내고 본문 텍스트만 남는다.
    assert "저장된 전체 본문" in str(by_url["https://n.example/full"]["text"])
    assert "**" not in str(by_url["https://n.example/full"]["text"])
    assert "짧은 설명만 있음" in str(by_url["https://n.example/short"]["text"])


def test_record_history_false_does_not_write_history(monkeypatch) -> None:
    """record_history=False면 수집·보고 이력을 남기지 않는다 (이력 오염 차단).

    리포트 생성이 비서를 호출할 때 쓰는 경로다. 이력을 남기면 그 사용자의 일간
    브리핑에서 같은 소식이 최대 7일간 가려진다.
    """
    _seed_collect_history()
    _patch_collect(monkeypatch, _make_docs)

    before_collect = len(history.get_collected_entries("minji", _TOPIC))
    before_reports = len(
        dedup.load_recent_report_items(
            "minji", _TOPIC, history=storage.get_store(), now=_NOW,
            lookback_days=365, exclude_today=False,
        )
    )

    result = pipeline.run_daily(_TOPIC, "minji", reference_now=_NOW, record_history=False)

    assert result["items"]  # 선별은 정상 동작한다
    # 이력은 한 건도 늘지 않는다.
    assert len(history.get_collected_entries("minji", _TOPIC)) == before_collect
    assert (
        len(
            dedup.load_recent_report_items(
                "minji", _TOPIC, history=storage.get_store(), now=_NOW,
                lookback_days=365, exclude_today=False,
            )
        )
        == before_reports
    )


def test_record_history_true_still_writes_history(monkeypatch) -> None:
    """기본값(True)은 기존대로 이력을 기록한다 (회귀 방지)."""
    _seed_collect_history()
    _patch_collect(monkeypatch, _make_docs)

    before = len(history.get_collected_entries("minji", _TOPIC))
    pipeline.run_daily(_TOPIC, "minji", reference_now=_NOW)

    assert len(history.get_collected_entries("minji", _TOPIC)) > before
