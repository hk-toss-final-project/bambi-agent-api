"""LangGraph Wiki 읽기 V2의 결정적 Seed 선택을 무상 평가하는 실행기.

실제 DB·Embedding·LLM을 호출하지 않고 10개 정상·경계 케이스에서 선택 성공률과
정밀도를 계산한다. Live 수집 품질은 기존 기능 벤치마크 범위이며 이 실행기는
V2에서 새로 도입한 결정적 Consumer 선택 정책만 회귀 검증한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.report_builder.api import select_wiki_seed_candidates
from shared.wiki_navigation_models import WikiNavigationCandidate

ROOT = Path(__file__).resolve().parent


def _args() -> argparse.Namespace:
    """결과 파일을 기록할지 결정하는 명령행 인자를 읽는다."""
    parser = argparse.ArgumentParser(description="Deterministic Wiki Read V2 benchmark")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _load_cases() -> list[dict[str, Any]]:
    """평가 JSONL을 순서대로 읽는다."""
    return [
        json.loads(line)
        for line in (ROOT / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _candidate(raw: list[object], rank: int, topic: str) -> WikiNavigationCandidate:
    """간결한 데이터셋 후보를 실제 Navigator 후보 계약으로 변환한다."""
    version_id, title, summary = (str(value) for value in raw[:3])
    vector_score = float(raw[3]) if len(raw) > 3 else None
    return WikiNavigationCandidate(
        document_id=f"doc-{version_id}",
        document_version_id=version_id,
        document_kind="concept",
        document_key=version_id,
        file_path=f"concepts/{version_id}.md",
        title=title,
        aliases=(),
        summary=summary,
        updated_at=datetime(2026, 8, 11, tzinfo=UTC),
        exact_match=title.casefold() in topic.casefold(),
        keyword_rank=rank,
        rrf_score=1.0 / (60 + rank),
        vector_score=vector_score,
    )


def _score(case: dict[str, Any]) -> dict[str, object]:
    """한 케이스의 선택 성공 여부와 Page 정밀도를 계산한다."""
    candidates = [
        _candidate(raw, rank, str(case["topic"]))
        for rank, raw in enumerate(case["candidates"], start=1)
    ]
    selected = {
        candidate.document_version_id
        for candidate in select_wiki_seed_candidates(str(case["topic"]), candidates)
    }
    expected_any = set(case.get("expected_any") or [])
    expected_all = set(case.get("expected_all") or [])
    forbidden = set(case.get("forbidden") or [])
    expected = expected_any | expected_all
    success = (
        (not expected_any or bool(selected & expected_any))
        and expected_all.issubset(selected)
        and not bool(selected & forbidden)
    )
    if not expected:
        success = success and not selected
    precision = len(selected & expected) / len(selected) if selected else float(not expected)
    return {
        "id": case["id"],
        "selected": sorted(selected),
        "success": success,
        "precision": precision,
    }


def _markdown(rows: list[dict[str, object]]) -> str:
    """케이스 결과와 집계 지표를 검토 가능한 Markdown으로 만든다."""
    success_count = sum(int(bool(row["success"])) for row in rows)
    mean_precision = sum(float(row["precision"]) for row in rows) / len(rows)
    lines = [
        "# Wiki Read V2 결정적 Seed 벤치마크",
        "",
        f"- 실행일: {datetime.now(UTC).date().isoformat()}",
        "- 모델·Provider: 없음(결정적 코드 경로)",
        "- Token·비용: 0",
        f"- 성공: {success_count}/{len(rows)} ({success_count / len(rows):.1%})",
        f"- 평균 Page Precision: {mean_precision:.3f}",
        "",
        "| 케이스 | 성공 | 선택 Page | Precision |",
        "|---|---:|---|---:|",
    ]
    lines.extend(
        f"| {row['id']} | {'Y' if row['success'] else 'N'} | "
        f"{', '.join(row['selected']) or '-'} | {float(row['precision']):.3f} |"
        for row in rows
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    """전체 케이스를 실행하고 선택적으로 결과 파일을 저장한다."""
    args = _args()
    rows = [_score(case) for case in _load_cases()]
    report = _markdown(rows)
    print(report, end="")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    return 0 if all(bool(row["success"]) for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
