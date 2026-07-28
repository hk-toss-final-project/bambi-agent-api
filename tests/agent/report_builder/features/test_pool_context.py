"""풀 우선 소비 판정(점수 컷오프·신선도·충분 여부)을 검증한다."""

from datetime import UTC, datetime, timedelta

from agent.report_builder.features import pool_context
from agent.report_builder.features.pool_context import (
    is_pool_sufficient,
    score_cutoff,
    select_pool_documents,
)
from shared.report_models import ReportContextDocument

_NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def _document(
    reference: str, score: float, *, namespace: str = "global", version_id: str = ""
) -> ReportContextDocument:
    """검증용 검색 결과 문서를 만든다."""
    return ReportContextDocument(
        reference=reference,
        document_version_id=version_id or f"ver-{reference}",
        chunk_id=f"chunk-{reference}",
        namespace_key=namespace,
        title=f"제목 {reference}",
        content="본문",
        url=None,
        score=score,
    )


def test_score_cutoff_combines_floor_and_ratio() -> None:
    """컷오프는 절대 하한과 상대 비율 중 큰 값이다.

    두 기준이 서로 다른 실패를 막는다. 상대 비율은 최고점에 한참 못 미치는 문서를
    걸러내고, 절대 하한은 최고점 자체가 잡음 수준일 때 풀 전체를 포기하게 한다.
    """
    # 관련 구간(0.089~0.098)에서는 상대 비율이 지배한다.
    assert score_cutoff(0.098) == 0.098 * pool_context.POOL_SCORE_RATIO
    # 잡음(0.000)에서는 절대 하한이 지배해 아무도 통과하지 못한다.
    assert score_cutoff(0.0) == pool_context.POOL_SCORE_FLOOR
    assert score_cutoff(0.0) > 0.0


def test_low_scoring_documents_are_dropped() -> None:
    """최고점 대비 크게 뒤처지는 문서는 근거에서 뺀다.

    실측 'DDD' 검색이 0.884와 0.057을 함께 반환했다 — 뒤엣것은 주제와 무관했다.
    """
    documents = [_document("G1", 0.884), _document("G2", 0.057)]

    selected = select_pool_documents(documents, now=_NOW)

    assert [d.reference for d in selected] == ["G1"]


def test_similar_high_scores_all_survive() -> None:
    """점수가 고르게 높으면 상대 컷이 아무도 떨어뜨리지 않는다."""
    documents = [_document(f"G{i}", score) for i, score in enumerate([0.90, 0.88, 0.86, 0.85, 0.84])]

    selected = select_pool_documents(documents, now=_NOW)

    assert len(selected) == 5


def test_personal_documents_are_not_pool_candidates() -> None:
    """개인 Wiki 문서는 판정 대상이 아니다.

    이 판정은 "실시간 수집을 대체할 풀 자료가 있는가"를 묻는 것이라,
    개인 문서가 많다고 수집을 생략하면 최신 근거가 통째로 빠진다.
    """
    documents = [
        _document("P1", 0.9, namespace="user/minji"),
        _document("P2", 0.8, namespace="user/minji"),
        _document("G1", 0.5),
    ]

    selected = select_pool_documents(documents, now=_NOW)

    assert [d.reference for d in selected] == ["G1"]


def test_stale_news_documents_are_dropped() -> None:
    """뉴스형 토픽에서 오래된 풀 문서는 제외한다.

    풀은 워커가 미리 채우는 창고라 자료가 늙는다. 어제 채운 풀을 믿고 오늘
    수집을 건너뛰면 당일 소식을 통째로 놓친다.
    """
    documents = [_document("G1", 0.5, version_id="fresh"), _document("G2", 0.5, version_id="stale")]
    published = {
        "fresh": _NOW - timedelta(hours=6),
        "stale": _NOW - timedelta(days=5),
    }

    selected = select_pool_documents(
        documents, published_at=published, topic_intent="news", now=_NOW
    )

    assert [d.reference for d in selected] == ["G1"]


def test_evergreen_topics_keep_older_documents() -> None:
    """개념형 토픽은 몇 달 전 자료도 근거로 인정한다."""
    documents = [_document("G1", 0.5, version_id="old")]
    published = {"old": _NOW - timedelta(days=45)}

    news = select_pool_documents(
        documents, published_at=published, topic_intent="news", now=_NOW
    )
    evergreen = select_pool_documents(
        documents, published_at=published, topic_intent="evergreen", now=_NOW
    )

    assert news == []
    assert [d.reference for d in evergreen] == ["G1"]


def test_documents_without_published_date_survive() -> None:
    """발행일을 모르는 문서는 그 이유만으로 버리지 않는다.

    "모르는 것"과 "오래된 것"은 다르다. 모른다고 버리면 쓸 수 있는 근거가 사라진다.
    """
    documents = [_document("G1", 0.5, version_id="unknown")]

    selected = select_pool_documents(documents, published_at={}, topic_intent="news", now=_NOW)

    assert [d.reference for d in selected] == ["G1"]


def test_sufficiency_threshold() -> None:
    """채택 문서가 기준 수 이상이면 실시간 수집을 생략할 수 있다."""
    minimum = pool_context.POOL_MIN_DOCUMENTS

    assert not is_pool_sufficient([_document(f"G{i}", 0.5) for i in range(minimum - 1)])
    assert is_pool_sufficient([_document(f"G{i}", 0.5) for i in range(minimum)])


def test_empty_pool_is_never_sufficient() -> None:
    """풀 결과가 없으면 반드시 실시간 수집으로 간다."""
    assert select_pool_documents([], now=_NOW) == []
    assert not is_pool_sufficient([])


def test_selection_is_sorted_by_score() -> None:
    """채택 결과는 점수 내림차순으로 반환한다(컷오프를 넉넉히 통과하는 값으로 검증)."""
    documents = [_document("G1", 0.70), _document("G2", 0.80), _document("G3", 0.75)]

    selected = select_pool_documents(documents, now=_NOW)

    assert [d.reference for d in selected] == ["G2", "G3", "G1"]


def test_all_noise_pool_is_rejected() -> None:
    """최고점 자체가 잡음 수준이면 풀 전체를 포기한다.

    상대 컷만 있으면 "잡음 중 상위"를 뽑아 통과시킨다. 풀 검색은 매칭이 없어도
    최근 문서를 채워 반환하되 점수를 0으로 남기므로(2026-07-28 실측: '양자컴퓨터'
    검색이 코스피·멜론 기사를 0.000으로 반환), 그 경우 실시간 수집으로 가야 한다.
    """
    noise = [_document(f"G{i}", 0.0) for i in range(5)]

    selected = select_pool_documents(noise, now=_NOW)

    assert selected == []
    assert not is_pool_sufficient(selected)


def test_genuine_match_clears_the_floor() -> None:
    """실제로 잘 맞는 문서는 절대 하한을 넘는다.

    실측된 두 구간(잡음 0.000 vs 관련 0.089~0.098)이 하한을 사이에 두고 갈리는지
    확인한다. 하한이 관련 구간 위로 올라가면 풀을 영원히 쓰지 못하고(앞선 값 0.35가
    그랬다 — 0/20건 통과), 0까지 내려가면 잡음이 전부 통과한다.
    """
    assert pool_context.POOL_SCORE_FLOOR > 0.0
    assert pool_context.POOL_SCORE_FLOOR < 0.089

    matched = [_document("G1", 0.098), _document("G2", 0.095), _document("G3", 0.089)]
    selected = select_pool_documents(matched, now=_NOW)

    assert len(selected) == 3
    assert is_pool_sufficient(selected)


def test_pool_content_is_cleaned_for_prompt() -> None:
    """풀 문서의 Jina 원문에서 사이트 메뉴 표기를 걷어내고 길이를 맞춘다.

    풀에는 페이지 전체가 Markdown으로 저장된다(2026-07-28 실측: 62,000자짜리
    '코스피 서킷브레이커' 기사 앞부분이 통째로 메뉴). 그대로 프롬프트에 넣으면
    LLM이 근거로 쓰지 않아, 풀 문서 4건을 받고도 개인 Wiki만 인용했다.
    """
    raw = (
        "[연합뉴스](https://www.yna.co.kr/)[본문 바로가기](https://x)\n\n"
        "*   [최신뉴스](https://a)\n*   [정치](https://b)\n\n"
        "코스피가 8% 급락하며 서킷브레이커가 발동했다."
    )
    document = ReportContextDocument(
        reference="G1",
        document_version_id="gsrc:1",
        chunk_id="gsrc:1",
        namespace_key="global",
        title="코스피 급락",
        content=raw,
        url="https://www.yna.co.kr/view/1",
        score=0.098,
    )

    selected = select_pool_documents([document], now=_NOW)

    assert len(selected) == 1
    cleaned = selected[0].content
    # 실제 기사 문장은 살아남는다.
    assert "서킷브레이커가 발동했다" in cleaned
    # Markdown 링크 표기는 사라진다.
    assert "https://" not in cleaned
    assert len(cleaned) < len(raw)


def test_empty_cleaning_result_keeps_original() -> None:
    """정제 결과가 비면 원문을 그대로 둔다 — 근거를 잃느니 지저분한 편이 낫다."""
    document = ReportContextDocument(
        reference="G1",
        document_version_id="gsrc:1",
        chunk_id="gsrc:1",
        namespace_key="global",
        title="제목",
        content="...",
        url=None,
        score=0.098,
    )

    selected = select_pool_documents([document], now=_NOW)

    assert selected[0].content
