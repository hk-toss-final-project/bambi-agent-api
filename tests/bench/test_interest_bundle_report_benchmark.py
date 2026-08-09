"""관심사 범주 리포트 LLM 벤치마크의 데이터셋과 비용 게이트를 검증한다."""

from bench.interest_bundle_report import run


def test_interest_bundle_benchmark_has_required_case_coverage() -> None:
    """데이터셋이 최소 10개이며 고립·영어·혼용 경계 케이스를 포함한다."""
    cases = run.load_cases()
    identifiers = {str(case["id"]) for case in cases}

    assert len(cases) >= 10
    assert {"isolated-root", "en-knowledge-graph", "mixed-llm-wiki"} <= identifiers


def test_interest_bundle_benchmark_estimates_nonzero_cost() -> None:
    """실제 호출 승인 전에 입력·출력 토큰과 예상 비용을 계산한다."""
    input_tokens, output_tokens = run.estimate_tokens(run.load_cases())
    cost = run.calculate_cost(
        input_tokens,
        output_tokens,
        input_cost_per_million=0.40,
        output_cost_per_million=1.60,
    )

    assert input_tokens > 0
    assert output_tokens > 0
    assert cost > 0


def test_interest_bundle_benchmark_builds_root_neighbor_and_global_references() -> None:
    """벤치마크 생성 근거가 루트·연결 노드·최신 자료를 구분해 제공한다."""
    case = next(case for case in run.load_cases() if case["id"] == "ko-ai-agent")

    contexts = run.build_contexts(case)

    assert [context.reference for context in contexts] == ["P1", "P2", "P3", "G1"]
    assert contexts[0].title == "생성형 AI"
    assert contexts[1].title == "AI 에이전트"
    assert [context.context_role for context in contexts[:3]] == [
        "wiki_root",
        "wiki_neighbor",
        "wiki_neighbor",
    ]
    assert contexts[0].source_updated_at == "2026-08-01T00:00:00+00:00"
