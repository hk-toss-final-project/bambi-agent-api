"""개인 Wiki Hybrid 검색 벤치마크의 데이터셋과 비용 게이트를 검증한다."""

from bench.wiki_hybrid_retrieval import run


def test_hybrid_benchmark_has_multilingual_boundary_cases() -> None:
    """최소 10개이며 혼용·동음이의·긴 Query·의미 전용 회수 케이스를 포함한다."""
    cases = run.load_cases()
    identifiers = {str(case["id"]) for case in cases}

    assert len(cases) >= 10
    assert {
        "mixed-llm-wiki",
        "ambiguous-agent",
        "long-distributed-query",
        "semantic-hbm",
    } <= identifiers


def test_hybrid_benchmark_estimates_nonzero_embedding_cost() -> None:
    """실제 호출 승인 전에 입력 토큰 상한과 예상 비용을 계산한다."""
    tokens = run.estimate_input_tokens(run.load_cases())
    cost = run.calculate_cost(tokens, cost_per_million=0.02)

    assert tokens > 0
    assert cost > 0


def test_hybrid_benchmark_dataset_has_valid_candidate_references() -> None:
    """Keyword·기대 ID는 각 케이스의 후보 집합 안에 있어야 한다."""
    for case in run.load_cases():
        candidate_ids = {str(candidate["id"]) for candidate in case["candidates"]}
        assert set(case["keyword_order"]) <= candidate_ids
        assert set(case["expected_ids"]) <= candidate_ids
