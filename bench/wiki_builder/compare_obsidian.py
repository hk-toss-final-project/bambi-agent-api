"""옵시디언 LLM Wiki와 자사 Wiki Builder의 결과 일치율을 비교한다.

같은 원본 클리핑을 두 엔진에 넣었을 때 만들어진 지식 Graph가 얼마나 겹치는지
측정한다. 정답지(Ground Truth) 없이 두 결과물의 합의 정도만 보므로, 어느 쪽이
옳은지가 아니라 "같은 결론에 도달하는지"를 판정한다.

- 입력: 원본 클리핑 Markdown 디렉터리(양쪽 엔진의 공통 입력)
- 비교 대상 1: 옵시디언 Vault의 entities/·concepts/ 문서와 위키링크
- 비교 대상 2: 자사 Builder가 같은 원본에서 추출한 Entity·Concept·관계

노드 이름은 표기 차이를 흡수하기 위해 하이픈·밑줄을 공백으로 바꾸고 대소문자를
무시하며, 양쪽이 선언한 aliases까지 같은 대상으로 취급한다. 관계는 옵시디언
위키링크가 방향을 보장하지 않으므로 방향을 무시하고 비교한다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

# OPENAI_API_KEY를 .env에서 읽는다(앱 진입점과 같은 방식).
load_dotenv(PROJECT_ROOT / ".env")

from agent.llm.api import complete_with_usage
from agent.wiki_builder.features import classification
from shared.wiki_models import ExistingWikiEntry

ROOT = Path(__file__).resolve().parent
_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
_SECTION = re.compile(r"^##\s+(.+?)\s*$", re.M)
# 옵시디언이 관계를 표현하는 두 섹션.
_LINK_SECTIONS = {"related entities", "related concepts"}


@dataclass(slots=True)
class Graph:
    """비교 대상 지식 Graph 하나를 담는다."""

    label: str
    # canonical name -> 표기 후보 집합
    nodes: dict[str, set[str]] = field(default_factory=dict)
    kinds: dict[str, str] = field(default_factory=dict)
    edges: set[frozenset[str]] = field(default_factory=set)

    def add_node(self, name: str, kind: str, aliases: list[str] | None = None) -> str:
        """노드를 등록하고 정규화된 대표 이름을 반환한다."""
        canonical = _canonical(name)
        if not canonical:
            return ""
        surfaces = self.nodes.setdefault(canonical, {canonical})
        for alias in aliases or []:
            alias_key = _canonical(alias)
            if alias_key:
                surfaces.add(alias_key)
        self.kinds.setdefault(canonical, kind)
        return canonical

    def add_edge(self, source: str, target: str) -> None:
        """방향을 무시한 관계를 등록한다."""
        left, right = _canonical(source), _canonical(target)
        if left and right and left != right:
            self.edges.add(frozenset({left, right}))


def _canonical(value: str) -> str:
    """표기 차이를 흡수한 비교용 이름을 만든다."""
    text = str(value or "").strip()
    text = text.split("|")[-1]  # 위키링크 표시 이름 우선
    text = text.split("/")[-1]  # 폴더 경로 제거
    text = re.sub(r"[-_]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().casefold()


def _frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Markdown 앞머리 YAML을 최소 규칙으로 읽고 본문과 분리한다."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, object] = {}
    current_key: str | None = None
    for line in parts[1].splitlines():
        if not line.strip():
            continue
        item = re.match(r"^\s*-\s+(.*)$", line)
        if item and current_key:
            values = meta.setdefault(current_key, [])
            if isinstance(values, list):
                values.append(item.group(1).strip().strip('"').strip("'"))
            continue
        pair = re.match(r"^([A-Za-z_][\w]*):\s*(.*)$", line)
        if pair:
            current_key = pair.group(1)
            raw = pair.group(2).strip()
            if raw.startswith("[") and raw.endswith("]"):
                meta[current_key] = [
                    piece.strip().strip('"').strip("'")
                    for piece in raw[1:-1].split(",")
                    if piece.strip()
                ]
            elif raw:
                meta[current_key] = raw.strip('"').strip("'")
            else:
                meta[current_key] = []
    return meta, parts[2]


def _as_list(value: object) -> list[str]:
    """Frontmatter 값을 문자열 목록으로 정규화한다."""
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def load_obsidian_graph(vault: Path) -> Graph:
    """옵시디언 Vault의 문서와 위키링크를 Graph로 변환한다."""
    graph = Graph(label="Obsidian")
    for kind, folder in (("entity", "entities"), ("concept", "concepts")):
        for path in sorted((vault / folder).glob("*.md")):
            text = path.read_text(encoding="utf-8")
            meta, body = _frontmatter(text)
            graph.add_node(path.stem, kind, _as_list(meta.get("aliases")))
            # 관계 섹션 안의 위키링크만 엣지로 취급한다.
            positions = [
                (match.start(), match.group(1).strip().casefold())
                for match in _SECTION.finditer(body)
            ]
            for index, (start, title) in enumerate(positions):
                if title not in _LINK_SECTIONS:
                    continue
                end = (
                    positions[index + 1][0]
                    if index + 1 < len(positions)
                    else len(body)
                )
                for link in _WIKILINK.findall(body[start:end]):
                    graph.add_edge(path.stem, link)
    return graph


def load_clippings(directory: Path) -> list[dict[str, object]]:
    """양쪽 엔진의 공통 입력인 원본 클리핑을 읽는다."""
    cases: list[dict[str, object]] = []
    for path in sorted(directory.glob("*.md")):
        meta, body = _frontmatter(path.read_text(encoding="utf-8"))
        cases.append(
            {
                "id": path.stem,
                "title": str(meta.get("title") or path.stem),
                "description": meta.get("description"),
                "tags": _as_list(meta.get("tags")),
                "content": body.strip(),
            }
        )
    return cases


def build_our_graph(
    cases: list[dict[str, object]],
    *,
    model: str,
    usage: dict[str, int],
    accumulate: bool = True,
) -> tuple[Graph, list[dict[str, object]]]:
    """자사 Builder를 원본마다 실행해 통합 Graph를 만든다.

    accumulate가 참이면 앞선 원본에서 만든 Entity·Concept을 다음 원본 분류에
    기존 목록으로 넘겨, 운영 Worker와 같은 증분 Build 조건을 재현한다.
    """
    graph = Graph(label="자사 Builder")
    rows: list[dict[str, object]] = []
    known_entities: dict[str, ExistingWikiEntry] = {}
    known_concepts: dict[str, ExistingWikiEntry] = {}
    for case in cases:
        started = time.perf_counter()
        error = ""
        try:
            result = classification.classify_source_for_wiki(
                source_title=str(case["title"]),
                source_content=str(case["content"]),
                source_description=case["description"],
                source_tags=list(case["tags"]),
                existing_entities=list(known_entities.values()),
                existing_concepts=list(known_concepts.values()),
                model=model,
            )
            if accumulate:
                for entity in result.entities:
                    key = _canonical(entity.name)
                    known_entities.setdefault(
                        key,
                        ExistingWikiEntry(
                            document_kind="entity",
                            document_key=key,
                            title=str(entity.name),
                            domain=getattr(entity, "subtype", None),
                            summary=getattr(entity, "description", None),
                        ),
                    )
                for concept in result.concepts:
                    key = _canonical(concept.title)
                    known_concepts.setdefault(
                        key,
                        ExistingWikiEntry(
                            document_kind="concept",
                            document_key=key,
                            title=str(concept.title),
                            domain=getattr(concept, "subtype", None),
                            summary=getattr(concept, "definition", None),
                        ),
                    )
            refs: dict[str, str] = {}
            for entity in result.entities:
                canonical = graph.add_node(entity.name, "entity", list(entity.aliases))
                refs[str(entity.name)] = canonical
            for concept in result.concepts:
                canonical = graph.add_node(
                    concept.title, "concept", list(concept.aliases)
                )
                refs[str(concept.title)] = canonical
            for relation in result.relations:
                graph.add_edge(relation.source_name, relation.target_name)
            rows.append(
                {
                    "id": case["id"],
                    "entities": len(result.entities),
                    "concepts": len(result.concepts),
                    "relations": len(result.relations),
                    "latency": time.perf_counter() - started,
                    "error": "",
                }
            )
        except Exception as exc:  # 실패한 원본도 결과에 남긴다.
            error = f"{type(exc).__name__}: {exc}"
            rows.append(
                {
                    "id": case["id"],
                    "entities": 0,
                    "concepts": 0,
                    "relations": 0,
                    "latency": time.perf_counter() - started,
                    "error": error,
                }
            )
    return graph, rows


def _surface_index(graph: Graph) -> tuple[dict[str, str], dict[str, str]]:
    """대표 이름 색인과 별칭 색인을 나누어 만든다.

    별칭이 다른 노드의 대표 이름을 가로채지 않도록 두 색인을 분리하고,
    비교할 때 대표 이름을 먼저 확인한다.
    """
    primary: dict[str, str] = {}
    aliases: dict[str, str] = {}
    for canonical in graph.nodes:
        primary.setdefault(canonical, canonical)
    for canonical, surfaces in graph.nodes.items():
        for surface in surfaces:
            if surface not in primary:
                aliases.setdefault(surface, canonical)
    return primary, aliases


def compare(ours: Graph, theirs: Graph) -> dict[str, object]:
    """두 Graph의 노드·관계 일치율을 계산한다."""
    their_primary, their_aliases = _surface_index(theirs)
    matched: dict[str, str] = {}
    taken: set[str] = set()
    # 1순위: 대표 이름끼리 정확히 일치하는 노드를 먼저 짝짓는다.
    for canonical in ours.nodes:
        if canonical in their_primary and canonical not in taken:
            matched[canonical] = canonical
            taken.add(canonical)
    # 2순위: 남은 노드만 별칭으로 짝짓되, 이미 짝지어진 상대는 건너뛴다.
    for canonical, surfaces in ours.nodes.items():
        if canonical in matched:
            continue
        for surface in sorted(surfaces):
            target = their_primary.get(surface) or their_aliases.get(surface)
            if target and target not in taken:
                matched[canonical] = target
                taken.add(target)
                break
    only_ours = sorted(set(ours.nodes) - set(matched))
    only_theirs = sorted(set(theirs.nodes) - set(matched.values()))

    # 공통 노드로 이름을 맞춘 뒤 관계를 비교한다.
    translated = {
        frozenset({matched[name] for name in edge})
        for edge in ours.edges
        if all(name in matched for name in edge)
    }
    translated.discard(frozenset())
    common_edges = translated & theirs.edges
    # 여러 표기가 상대의 같은 노드에 붙을 수 있어(우리 쪽 중복 노드) 교집합
    # 크기는 상대 노드 기준으로 세고, 커버리지는 양방향으로 따로 보고한다.
    their_matched = set(matched.values())
    edge_total = len(translated | theirs.edges)
    union = len(ours.nodes) + len(theirs.nodes) - len(their_matched)
    return {
        "matched_nodes": sorted(matched),
        "only_ours": only_ours,
        "only_theirs": only_theirs,
        "their_matched": len(their_matched),
        "our_matched": len(matched),
        "their_coverage": (
            len(their_matched) / len(theirs.nodes) if theirs.nodes else 0.0
        ),
        "our_coverage": len(matched) / len(ours.nodes) if ours.nodes else 0.0,
        "node_agreement": len(their_matched) / union if union else 0.0,
        "our_edges": len(ours.edges),
        "their_edges": len(theirs.edges),
        "comparable_edges": len(translated),
        "common_edges": sorted("  ↔  ".join(sorted(edge)) for edge in common_edges),
        "edge_agreement": len(common_edges) / edge_total if edge_total else 0.0,
    }


def dump_graph(
    graph: Graph, rows: list[dict[str, object]], path: Path
) -> None:
    """지표를 다시 계산할 때 LLM을 재호출하지 않도록 Graph를 저장한다."""
    path.write_text(
        json.dumps(
            {
                "label": graph.label,
                "nodes": {key: sorted(value) for key, value in graph.nodes.items()},
                "kinds": graph.kinds,
                "edges": [sorted(edge) for edge in graph.edges],
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def load_graph(path: Path) -> tuple[Graph, list[dict[str, object]]]:
    """저장해 둔 Graph를 되살린다."""
    data = json.loads(path.read_text(encoding="utf-8"))
    graph = Graph(label=str(data["label"]))
    graph.nodes = {key: set(value) for key, value in data["nodes"].items()}
    graph.kinds = dict(data["kinds"])
    graph.edges = {frozenset(edge) for edge in data["edges"]}
    return graph, list(data.get("rows", []))


def _args() -> argparse.Namespace:
    """비교 실행 옵션을 파싱한다."""
    parser = argparse.ArgumentParser(description="Obsidian vs 자사 Wiki Builder 비교")
    parser.add_argument("--vault", required=True, help="옵시디언 Vault 경로")
    parser.add_argument("--clippings", required=True, help="공통 원본 클리핑 경로")
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--input-cost-per-million", type=float, required=True)
    parser.add_argument("--output-cost-per-million", type=float, required=True)
    parser.add_argument(
        "--independent",
        action="store_true",
        help="원본을 서로 독립 분류한다(기존 Entity를 넘기지 않음)",
    )
    parser.add_argument(
        "--from-cache",
        action="store_true",
        help="지난 실행에서 저장한 자사 Graph를 재사용한다(LLM 호출 없음)",
    )
    return parser.parse_args()


def main() -> None:
    """두 엔진의 결과를 비교하고 Markdown 보고서를 남긴다."""
    args = _args()
    usage = {"input": 0, "output": 0}

    def tracked_complete(system_prompt: str, user_prompt: str, model: str) -> str:
        """공유 LLM 경계로 호출하고 토큰 사용량을 누적한다."""
        completion = complete_with_usage(
            system_prompt, user_prompt, model=args.model, temperature=0
        )
        usage["input"] += completion.input_tokens
        usage["output"] += completion.output_tokens
        return completion.text

    cases = load_clippings(Path(args.clippings))
    theirs = load_obsidian_graph(Path(args.vault))

    result_dir = ROOT / "results"
    result_dir.mkdir(exist_ok=True)
    mode = "independent" if args.independent else "accumulate"
    cache_path = result_dir / f"our_graph_{args.model}_{mode}.json"

    if args.from_cache and cache_path.exists():
        ours, rows = load_graph(cache_path)
    else:
        original = classification.complete
        classification.complete = tracked_complete
        try:
            ours, rows = build_our_graph(
                cases,
                model=args.model,
                usage=usage,
                accumulate=not args.independent,
            )
        finally:
            classification.complete = original
        dump_graph(ours, rows, cache_path)

    report = compare(ours, theirs)
    now = datetime.now(UTC)
    cost = (
        usage["input"] * args.input_cost_per_million
        + usage["output"] * args.output_cost_per_million
    ) / 1_000_000

    lines = [
        "# 옵시디언 vs 자사 Wiki Builder 결과 일치율",
        "",
        f"- 실행 날짜: {now.isoformat()}",
        f"- 모델: {args.model}",
        f"- 공통 원본: {len(cases)}건 ({args.clippings})",
        f"- 옵시디언 Vault: {args.vault}",
        f"- 자사 실행 모드: {'독립 분류' if args.independent else '증분 누적(운영과 동일)'}",
        "",
        "## 규모 비교",
        "",
        "| 항목 | 자사 Builder | 옵시디언 |",
        "|---|---:|---:|",
        f"| 노드 | {len(ours.nodes)} | {len(theirs.nodes)} |",
        f"| 관계 | {report['our_edges']} | {report['their_edges']} |",
        "",
        "## 일치율",
        "",
        f"- 노드 일치율(Jaccard): {report['node_agreement']:.2%}",
        f"- 옵시디언 노드 중 자사도 만든 비율: {report['their_coverage']:.2%} "
        f"({report['their_matched']}/{len(theirs.nodes)})",
        f"- 자사 노드 중 옵시디언에도 있는 비율: {report['our_coverage']:.2%} "
        f"({report['our_matched']}/{len(ours.nodes)})",
        f"- 관계 일치율: {report['edge_agreement']:.2%} "
        f"(공통 {len(report['common_edges'])}개)",
        f"- 자사에만 있는 노드: {len(report['only_ours'])}개",
        f"- 옵시디언에만 있는 노드: {len(report['only_theirs'])}개",
        f"- 입력 토큰: {usage['input']} / 출력 토큰: {usage['output']}",
        f"- 예상 비용: ${cost:.6f}",
        "",
        "## 양쪽이 함께 만든 노드",
        "",
        ", ".join(report["matched_nodes"]) or "(없음)",
        "",
        "## 자사 Builder에만 있는 노드",
        "",
        ", ".join(report["only_ours"]) or "(없음)",
        "",
        "## 옵시디언에만 있는 노드",
        "",
        ", ".join(report["only_theirs"]) or "(없음)",
        "",
        "## 양쪽이 함께 만든 관계",
        "",
        *(
            [f"- {edge}" for edge in report["common_edges"]]
            or ["(없음)"]
        ),
        "",
        "## 원본별 자사 Builder 추출량",
        "",
        "| 원본 | Entity | Concept | 관계 | 지연 | 오류 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {str(row['id'])[:40]} | {row['entities']} | {row['concepts']} | "
            f"{row['relations']} | {float(row['latency']):.2f}s | {row['error']} |"
        )

    path = result_dir / f"comparison_{now.date().isoformat()}_{args.model}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
