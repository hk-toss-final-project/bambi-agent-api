"""자사 Builder·llm_wiki 앱·llm-wiki.md 패턴 세 결과물을 함께 비교한다.

같은 원본 클리핑을 세 방식에 넣었을 때 만들어진 지식 Graph가 서로 얼마나
겹치는지 측정한다. 정답지 없이 합의 정도만 보므로 어느 쪽이 옳은지가 아니라
"같은 결론에 도달하는지"를 판정한다.

- 1번 자사 Builder: agent/wiki_builder 분류 파이프라인 (증분 누적 모드)
- 2번 llm_wiki 앱: nashsu/llm_wiki 데스크톱 앱이 만든 Vault
- 3번 llm-wiki.md 패턴: 같은 저장소의 패턴 문서를 그대로 수행한 Vault

세 비교군의 모델이 다르면 도구 차이와 모델 차이가 섞이므로, 실행에 사용한
모델을 보고서에 함께 남긴다.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bench.wiki_builder.compare_obsidian import (  # noqa: E402
    Graph,
    build_our_graph,
    compare,
    dump_graph,
    load_clippings,
    load_graph,
    load_obsidian_graph,
)

ROOT = Path(__file__).resolve().parent


def _args() -> argparse.Namespace:
    """세 비교군 경로와 실행 옵션을 파싱한다."""
    parser = argparse.ArgumentParser(description="LLM Wiki 3자 비교")
    parser.add_argument("--clippings", required=True, help="공통 원본 클리핑 경로")
    parser.add_argument("--app-vault", required=True, help="2번 llm_wiki 앱 Vault")
    parser.add_argument(
        "--pattern-vault",
        default=str(ROOT / "pattern_vault"),
        help="3번 llm-wiki.md 패턴 Vault",
    )
    parser.add_argument("--model", default="gpt-4.1-mini", help="자사 Builder 모델")
    parser.add_argument("--app-model", default="gpt-4o-mini", help="2번 실행 모델(기록용)")
    parser.add_argument(
        "--pattern-model", default="gpt-4o-mini", help="3번 실행 모델(기록용)"
    )
    parser.add_argument("--input-cost-per-million", type=float, default=0.0)
    parser.add_argument("--output-cost-per-million", type=float, default=0.0)
    parser.add_argument(
        "--from-cache",
        action="store_true",
        help="자사 Builder Graph를 캐시에서 읽는다(LLM 호출 없음)",
    )
    return parser.parse_args()


def _pair_rows(graphs: dict[str, Graph]) -> list[str]:
    """세 비교군의 모든 짝에 대해 일치율 표 행을 만든다."""
    rows: list[str] = []
    for left, right in combinations(graphs, 2):
        report = compare(graphs[left], graphs[right])
        rows.append(
            f"| {left} ↔ {right} | {report['node_agreement']:.2%} | "
            f"{report['their_matched']} | {report['edge_agreement']:.2%} | "
            f"{len(report['common_edges'])} |"
        )
    return rows


def main() -> None:
    """세 Graph를 만들고 짝별 일치율 보고서를 남긴다."""
    args = _args()
    usage = {"input": 0, "output": 0}
    result_dir = ROOT / "results"
    result_dir.mkdir(exist_ok=True)
    cache_path = result_dir / f"our_graph_{args.model}_accumulate.json"

    if args.from_cache and cache_path.exists():
        ours, _rows = load_graph(cache_path)
    else:
        from agent.llm.api import complete_with_usage
        from agent.wiki_builder.features import classification

        def tracked_complete(system_prompt: str, user_prompt: str, model: str) -> str:
            """공유 LLM 경계로 호출하고 토큰 사용량을 누적한다."""
            completion = complete_with_usage(
                system_prompt, user_prompt, model=args.model, temperature=0
            )
            usage["input"] += completion.input_tokens
            usage["output"] += completion.output_tokens
            return completion.text

        cases = load_clippings(Path(args.clippings))
        original = classification.complete
        classification.complete = tracked_complete
        try:
            ours, rows = build_our_graph(
                cases, model=args.model, usage=usage, accumulate=True
            )
        finally:
            classification.complete = original
        dump_graph(ours, rows, cache_path)

    ours.label = "1번 자사 Builder"
    app = load_obsidian_graph(Path(args.app_vault))
    app.label = "2번 llm_wiki 앱"
    pattern = load_obsidian_graph(Path(args.pattern_vault))
    pattern.label = "3번 패턴"

    graphs = {ours.label: ours, app.label: app, pattern.label: pattern}
    now = datetime.now(UTC)
    cost = (
        usage["input"] * args.input_cost_per_million
        + usage["output"] * args.output_cost_per_million
    ) / 1_000_000

    lines = [
        "# LLM Wiki 3자 비교 — 자사 Builder vs llm_wiki 앱 vs llm-wiki.md 패턴",
        "",
        f"- 실행 날짜: {now.isoformat()}",
        f"- 공통 원본: {args.clippings}",
        "",
        "## 비교군",
        "",
        "| 비교군 | 모델 | 노드 | 관계 |",
        "|---|---|---:|---:|",
        f"| 1번 자사 Builder | {args.model} | {len(ours.nodes)} | {len(ours.edges)} |",
        f"| 2번 llm_wiki 앱 | {args.app_model} | {len(app.nodes)} | {len(app.edges)} |",
        f"| 3번 패턴 | {args.pattern_model} | {len(pattern.nodes)} | "
        f"{len(pattern.edges)} |",
        "",
        "## 짝별 일치율",
        "",
        "| 짝 | 노드 Jaccard | 공통 노드 | 관계 일치율 | 공통 관계 |",
        "|---|---:|---:|---:|---:|",
        *_pair_rows(graphs),
        "",
    ]
    for left, right in combinations(graphs, 2):
        report = compare(graphs[left], graphs[right])
        lines.extend(
            [
                f"## {left} ↔ {right}",
                "",
                f"- 공통 노드({report['their_matched']}개): "
                + (", ".join(report["matched_nodes"]) or "(없음)"),
                f"- {left}에만: " + (", ".join(report["only_ours"]) or "(없음)"),
                f"- {right}에만: " + (", ".join(report["only_theirs"]) or "(없음)"),
                "",
            ]
        )
    if cost:
        lines.append(f"- 자사 Builder 실행 비용: ${cost:.6f}")
        lines.append("")

    path = result_dir / f"compare3_{now.date().isoformat()}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
