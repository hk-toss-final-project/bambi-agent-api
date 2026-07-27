"""선별 결과 원인 분류(outcomes) 검증. 순수 함수라 외부 호출이 없다."""

from agent.selection.features import outcomes


def _selection(mode: str = "weekly", *, items=None, **log) -> dict:
    """run_daily 반환 모양의 최소 딕셔너리를 만든다."""
    base_log = {
        "source_attempted": 3,
        "source_failures": [],
        "collected": 0,
        "exclusions": [],
    }
    base_log.update(log)
    return {"mode": mode, "items": items or [], "log": base_log, "errors": []}


def test_success_when_daily_items_exist() -> None:
    """당일 아이템이 있으면 success다."""
    assert outcomes.classify(_selection("daily", items=[{"title": "x"}])) == outcomes.SUCCESS


def test_daily_mode_without_items_is_not_success() -> None:
    """mode가 daily여도 아이템이 비었으면 success로 보지 않는다."""
    assert outcomes.classify(_selection("daily", items=[])) != outcomes.SUCCESS


def test_all_sources_failed_is_provider_failure() -> None:
    """소스가 전부 실패하면 외부 장애로 분류한다(검색어 문제 아님)."""
    selection = _selection(source_failures=["뉴스", "YouTube", "Reddit"], collected=0)
    assert outcomes.classify(selection) == outcomes.PROVIDER_FAILURE


def test_partial_failure_with_zero_collected_is_provider_failure() -> None:
    """일부만 실패했어도 수집이 0건이면 외부 장애로 본다."""
    selection = _selection(source_failures=["뉴스"], collected=0)
    assert outcomes.classify(selection) == outcomes.PROVIDER_FAILURE


def test_partial_failure_with_documents_is_not_provider_failure() -> None:
    """일부 실패했지만 문서가 모였다면 장애로 단정하지 않는다."""
    selection = _selection(
        source_failures=["Reddit"], collected=10, after_basic_filter=8, after_similarity_filter=0
    )
    assert outcomes.classify(selection) == outcomes.LOW_RELEVANCE


def test_embedding_failure_is_provider_failure() -> None:
    """임베딩(OpenAI) 실패도 외부 장애로 분류한다."""
    selection = _selection(embedding_failed=True, collected=10, after_basic_filter=10)
    assert outcomes.classify(selection) == outcomes.PROVIDER_FAILURE


def test_zero_collected_is_no_results() -> None:
    """장애 없이 수집이 0건이면 검색 결과 없음이다."""
    assert outcomes.classify(_selection(collected=0)) == outcomes.NO_RESULTS


def test_all_filtered_by_basic_filter_is_no_results() -> None:
    """수집은 됐지만 기초 필터에서 전멸하면 결과 없음으로 본다."""
    selection = _selection(collected=12, after_basic_filter=0)
    assert outcomes.classify(selection) == outcomes.NO_RESULTS


def test_similarity_wipeout_is_low_relevance() -> None:
    """유사도 필터에서 전멸하면 관련도 부족이다."""
    selection = _selection(collected=12, after_basic_filter=10, after_similarity_filter=0)
    assert outcomes.classify(selection) == outcomes.LOW_RELEVANCE


def test_all_clusters_deduped_is_duplicate_only() -> None:
    """클러스터가 전부 중복 제거되면 '이미 다룬 소식뿐'으로 분류한다."""
    selection = _selection(
        collected=12,
        after_basic_filter=10,
        after_similarity_filter=8,
        clusters=2,
        exclusions=[{"stage": "dedup"}, {"stage": "dedup"}],
    )
    assert outcomes.classify(selection) == outcomes.DUPLICATE_ONLY


def test_threshold_wipeout_is_below_threshold() -> None:
    """중복은 아니고 임계값에서 걸러졌으면 점수 미달로 분류한다."""
    selection = _selection(
        collected=12,
        after_basic_filter=10,
        after_similarity_filter=8,
        clusters=2,
        exclusions=[{"stage": "threshold"}],
    )
    assert outcomes.classify(selection) == outcomes.BELOW_THRESHOLD


def test_only_search_quality_outcomes_are_reformulatable() -> None:
    """검색어로 고쳐질 수 있는 원인에서만 재구성을 허용한다."""
    assert outcomes.should_reformulate(outcomes.NO_RESULTS)
    assert outcomes.should_reformulate(outcomes.LOW_RELEVANCE)
    # 외부 장애·중복 소식·점수 미달은 검색어를 바꿔도 해결되지 않는다.
    assert not outcomes.should_reformulate(outcomes.PROVIDER_FAILURE)
    assert not outcomes.should_reformulate(outcomes.DUPLICATE_ONLY)
    assert not outcomes.should_reformulate(outcomes.BELOW_THRESHOLD)
    assert not outcomes.should_reformulate(outcomes.SUCCESS)
    assert not outcomes.should_reformulate(outcomes.UNKNOWN)


def test_describe_returns_korean_for_every_outcome() -> None:
    """모든 원인 코드에 한국어 설명이 있다(화면·trace 노출용)."""
    for outcome in (
        outcomes.SUCCESS,
        outcomes.PROVIDER_FAILURE,
        outcomes.NO_RESULTS,
        outcomes.LOW_RELEVANCE,
        outcomes.DUPLICATE_ONLY,
        outcomes.BELOW_THRESHOLD,
        outcomes.UNKNOWN,
    ):
        assert outcomes.describe(outcome)
        assert outcomes.describe(outcome) != outcome
