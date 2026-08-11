"""LangGraph Wiki 유지 V2의 결정적 계획 정책을 무상 평가하는 실행기.

DB·Embedding·LLM을 호출하지 않고 정상·경계 감사 결과가 noop, 파생 복구,
전체 재구성 중 기대한 최소 실행 범위로 분기되는지 회귀 검증한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.wiki_builder.api import WikiMaintenanceAudit, plan_wiki_maintenance

ROOT = Path(__file__).resolve().parent
ACTIVATED_AT = datetime(2026, 8, 11, 12, tzinfo=UTC)


def _args() -> argparse.Namespace:
    """결과 파일을 기록할지 결정하는 명령행 인자를 읽는다."""
    parser = argparse.ArgumentParser(
        description="Deterministic Wiki Maintenance V2 benchmark"
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _load_cases() -> list[dict[str, Any]]:
    """평가 JSONL을 순서대로 읽는다."""
    return [
        json.loads(line)
        for line in (ROOT / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _audit(case: dict[str, Any]) -> WikiMaintenanceAudit:
    """간결한 데이터셋을 실제 유지 감사 계약으로 변환한다."""
    activated_at = ACTIVATED_AT if case["activated"] else None
    latest_source_at = ACTIVATED_AT + timedelta(
        minutes=int(case["source_age_minutes"])
    )
    return WikiMaintenanceAudit(
        user_id="benchmark-user",
        source_count=int(case["source_count"]),
        latest_source_updated_at=latest_source_at,
        active_wiki_version_id=("benchmark-wiki" if case["active_wiki"] else None),
        active_wiki_activated_at=activated_at,
        quality_metrics=dict(case["quality_metrics"]),
        missing_embedding_document_version_ids=tuple(case["missing_embedding_ids"]),
    )


def _score(case: dict[str, Any]) -> dict[str, object]:
    """한 감사 케이스의 계획을 계산하고 기대 action과 비교한다."""
    plan = plan_wiki_maintenance(_audit(case), trigger=str(case["trigger"]))
    expected = str(case["expected_action"])
    return {
        "id": str(case["id"]),
        "expected": expected,
        "actual": plan.action.value,
        "success": plan.action.value == expected,
    }


def _markdown(rows: list[dict[str, object]]) -> str:
    """케이스 결과와 집계 지표를 검토 가능한 Markdown으로 만든다."""
    success_count = sum(int(bool(row["success"])) for row in rows)
    lines = [
        "# Wiki Maintenance V2 결정적 계획 벤치마크",
        "",
        f"- 실행일: {datetime.now(UTC).date().isoformat()}",
        "- 모델·Provider: 없음(결정적 코드 경로)",
        "- Token·비용: 0",
        f"- 성공: {success_count}/{len(rows)} ({success_count / len(rows):.1%})",
        "",
        "| 케이스 | 기대 | 실제 | 성공 |",
        "|---|---|---|---:|",
    ]
    lines.extend(
        f"| {row['id']} | {row['expected']} | {row['actual']} | "
        f"{'Y' if row['success'] else 'N'} |"
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
