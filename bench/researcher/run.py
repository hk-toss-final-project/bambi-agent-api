"""조사원 에이전트가 검색어를 얼마나 잘 고르는지 실제 LLM으로 측정한다.

조사원은 "어떤 문서를 쓸까"가 아니라 **"어떤 검색어로 찾을까"**를 정한다.
검색 결과는 그대로 수집되므로, 측정 대상은 문서 선택이 아니라 **질의 선택**이다.

    확장 도달률 : 주제어만으로는 안 나오는 문서를, 연관어로 확장해 찾아냈는가
    수집 판단   : 실시간 수집(collect_live)을 불러야 할 때만 불렀는가
    잡음률      : 주제와 무관한 문서를 끌어왔는가

**`expect_live` 판정 기준**: 케이스의 창고(`pool`)에서 얻을 수 있는 관련 문서가
`POOL_MIN_DOCUMENTS`(=3)에 못 미치면 `true`다. 코드의 `is_pool_sufficient`와
같은 기준을 쓴다. 2026-07-31 최초 데이터셋은 이 기준 없이 작성돼 2건짜리
케이스 4건을 `false`로 잘못 적었고, 사용자 승인을 받아 정정했다.

**검색은 고정 코퍼스로 대체한다.** 실제 DB를 쓰면 내용이 바뀔 때마다 결과가
달라져 회귀 비교가 불가능하다. 케이스마다 정의한 `pool`을 대상으로,
키워드가 질의에 포함되면(또는 그 반대면) 맞은 것으로 본다.

대체하는 위치는 **DB 호출(`prag_003`)**이다. 예전에는 `search_stored_documents`
자체를 갈아끼웠는데, 그러면 그 함수 안의 컷오프(개인 Wiki 점수 하한·풀 선별)가
통째로 건너뛰어져 회귀를 잡지 못했다 — 2026-08-05에 개인 Wiki 잡음이 실시간
수집을 막던 버그가 이 벤치마크를 100%로 통과했다. 이제 한 단계 아래를 대체해
실제 컷오프 코드가 실행된다.

코퍼스 항목은 `namespace`("global"|"wiki"), `document_id`(같은 문서의 청크를
표현), `score`를 선택적으로 가진다. 생략하면 각각 "global", 항목 `id`, 1.0이다.

비용이 발생하므로 --confirm-cost를 명시해야 실행된다.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import selectors
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
PROJECT_ROOT = ROOT.parents[1]

# OPENAI_API_KEY를 .env에서 읽는다(다른 벤치마크와 같은 방식).
load_dotenv(PROJECT_ROOT / ".env")

from agent.report_builder.features import researcher  # noqa: E402
from agent.report_builder.features.researcher import research_context  # noqa: E402
from shared.report_models import ReportContextDocument  # noqa: E402

DATASET = ROOT / "dataset.jsonl"


def load_cases() -> list[dict[str, object]]:
    """JSONL 벤치마크 데이터셋을 순서대로 읽는다."""
    return [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def matches(document: dict[str, object], query: str) -> bool:
    """고정 코퍼스 검색의 일치 규칙.

    키워드가 질의에 들어 있거나 질의가 키워드에 들어 있으면 맞은 것으로 본다.
    실제 검색(trigram·벡터)의 부분 일치 성질을 단순화해 흉내 낸다.
    """
    lowered = query.strip().lower()
    if not lowered:
        return False
    for keyword in document.get("keywords", []):  # type: ignore[union-attr]
        key = str(keyword).lower()
        if key in lowered or lowered in key:
            return True
    return False


def entry_namespace(entry: dict[str, object]) -> str:
    """코퍼스 항목의 출처 구분을 반환한다. 생략하면 창고(global)로 본다."""
    return str(entry.get("namespace", "global"))


def entry_document_id(entry: dict[str, object]) -> str:
    """코퍼스 항목이 속한 문서 ID를 반환한다.

    여러 항목이 같은 `document_id`를 가지면 한 문서의 청크를 뜻한다. 실시간 수집
    판정은 이 ID 단위로 세므로, 청크가 여러 건이어도 1건으로 계산돼야 한다.
    """
    return str(entry.get("document_id", entry["id"]))


def to_context(entry: dict[str, object], reference: str) -> ReportContextDocument:
    """코퍼스 항목을 근거 문서로 만든다."""
    return ReportContextDocument(
        reference=reference,
        document_version_id=entry_document_id(entry),
        chunk_id=f"chunk-{entry['id']}",
        namespace_key=entry_namespace(entry),
        title=str(entry["title"]),
        content=str(entry["content"]),
        url=None,
        score=float(entry.get("score", 1.0)),  # type: ignore[arg-type]
    )


class _FakeConnection:
    """transaction()만 지원하는 DB 연결 Test Double."""

    @asynccontextmanager
    async def transaction(self):  # type: ignore[no-untyped-def]
        """아무것도 하지 않는 트랜잭션 구간을 연다."""
        yield self


async def _skip_scope(connection: object, *, user_id: str) -> None:
    """RLS Scope 설정을 생략한다."""


async def _skip_freshness(
    connection: object, ids: list[str]
) -> dict[str, object]:
    """발행 시각 조회를 생략한다. 비어 있으면 신선도 검사를 건너뛴다."""
    return {}


class Recorder:
    """한 케이스 동안 도구가 무엇을 했는지 기록한다."""

    def __init__(self, case: dict[str, object]) -> None:
        """케이스의 코퍼스를 준비한다."""
        self.case = case
        self.queries: list[str] = []
        self.live_called = False

    async def search(
        self, connection: object, *, user_id: str, query: str, **kwargs: object
    ) -> list[ReportContextDocument]:
        """DB 검색(prag_003) 자리에서 고정 코퍼스의 일치 문서를 반환한다.

        개인 Wiki(P)와 창고(G) 참조 번호를 각각 매긴다. 컷오프는 여기서 하지
        않는다 — 실제 `search_stored_documents`가 적용하는지를 보는 것이 목적이다.
        """
        self.queries.append(query)
        pool = self.case.get("pool", [])  # type: ignore[union-attr]
        documents: list[ReportContextDocument] = []
        counters: dict[str, int] = {}
        for entry in pool:  # type: ignore[union-attr]
            if not matches(entry, query):
                continue
            prefix = "G" if entry_namespace(entry) == "global" else "P"
            counters[prefix] = counters.get(prefix, 0) + 1
            documents.append(to_context(entry, f"{prefix}{counters[prefix]}"))
        return documents

    def collect(self, topic: str, user_id: str, *, model: str = "") -> list[
        ReportContextDocument
    ]:
        """실시간 수집 호출을 기록하고 케이스가 정의한 결과를 반환한다."""
        self.live_called = True
        live = self.case.get("live", [])  # type: ignore[union-attr]
        return [
            to_context(entry, f"L{index}")
            for index, entry in enumerate(live, start=1)  # type: ignore[arg-type]
        ]


def collected_ids(outcome_documents: tuple[ReportContextDocument, ...]) -> set[str]:
    """수집된 문서의 코퍼스 ID 집합을 만든다."""
    return {document.document_version_id for document in outcome_documents}


async def run_cases(
    cases: list[dict[str, object]], model: str
) -> list[dict[str, object]]:
    """모든 케이스를 조사시키고 질의 선택·수집 판단을 기록한다."""
    results: list[dict[str, object]] = []
    for case in cases:
        recorder = Recorder(case)
        # DB 호출만 대체한다. search_stored_documents 안의 컷오프는 실제 코드가
        # 실행돼야 개인 Wiki 잡음·청크 중복 회귀를 잡을 수 있다.
        researcher.prag_003 = recorder.search  # type: ignore[assignment]
        researcher.set_personal_wiki_scope = _skip_scope  # type: ignore[assignment]
        researcher.load_global_document_freshness = _skip_freshness  # type: ignore[assignment]
        researcher.collect_live_context = recorder.collect  # type: ignore[assignment]

        started = time.perf_counter()
        outcome = await research_context(
            _FakeConnection(),  # type: ignore[arg-type]
            topic=str(case["topic"]),
            user_id="bench-user",
            model=model,
        )
        found = collected_ids(outcome.documents)
        must_find = set(case.get("must_find", []))  # type: ignore[arg-type]
        # 근거에 남으면 안 되는 항목. 문서 ID로 비교한다(청크는 같은 문서다).
        irrelevant = {
            entry_document_id(entry)
            for entry in case.get("pool", [])  # type: ignore[union-attr]
            if not entry.get("relevant", True)
        }
        expect_live = bool(case["expect_live"])
        results.append(
            {
                "id": case["id"],
                "kind": case["kind"],
                "queries": recorder.queries,
                "expansion_found": sorted(must_find & found),
                "expansion_missed": sorted(must_find - found),
                "expansion_ok": must_find <= found,
                "noise_collected": sorted(irrelevant & found),
                "expect_live": expect_live,
                "live_called": recorder.live_called,
                "live_ok": expect_live == recorder.live_called,
                "documents": len(outcome.documents),
                "tool_calls": len(outcome.calls),
                "stop_reason": outcome.stop_reason,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "input_tokens": outcome.input_tokens,
                "output_tokens": outcome.output_tokens,
            }
        )
        marks = []
        marks.append("확장OK" if must_find <= found else "확장놓침")
        marks.append("수집OK" if expect_live == recorder.live_called else "수집오판")
        if irrelevant & found:
            marks.append("잡음")
        print(
            f"[{' '.join(marks):<16}] {case['id']:<22} "
            f"질의={recorder.queries} 문서={len(outcome.documents)}",
            flush=True,
        )
    return results


def summarize(results: list[dict[str, object]]) -> dict[str, object]:
    """케이스별 결과를 집계 지표로 요약한다."""
    total = len(results)
    expansion_cases = [r for r in results if r["expansion_found"] or r["expansion_missed"]]
    found = sum(len(r["expansion_found"]) for r in results)  # type: ignore[arg-type]
    missed = sum(len(r["expansion_missed"]) for r in results)  # type: ignore[arg-type]
    return {
        "total": total,
        "expansion_cases": len(expansion_cases),
        "expansion_targets": found + missed,
        "expansion_recall": round(found / (found + missed), 3) if found + missed else 0.0,
        "expansion_case_pass": sum(1 for r in results if r["expansion_ok"]),
        "live_decision_accuracy": round(
            sum(1 for r in results if r["live_ok"]) / total, 3
        ),
        "noise_cases": sum(1 for r in results if r["noise_collected"]),
        "avg_tool_calls": round(
            sum(int(r["tool_calls"]) for r in results) / total, 2
        ),
        "max_iterations_hit": sum(
            1 for r in results if r["stop_reason"] == "max_iterations"
        ),
        "avg_latency_ms": int(sum(int(r["latency_ms"]) for r in results) / total),
        "input_tokens": sum(int(r["input_tokens"]) for r in results),
        "output_tokens": sum(int(r["output_tokens"]) for r in results),
    }


def main() -> int:
    """비용 확인 후 전체 벤치마크를 실행하고 결과를 출력한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--confirm-cost", action="store_true")
    args = parser.parse_args()

    cases = load_cases()
    estimated = sum(len(json.dumps(c, ensure_ascii=False)) for c in cases) // 4 * 4
    print(f"cases={len(cases)}, estimated_input_tokens≈{estimated}")
    if not args.confirm_cost:
        print("실제 호출을 실행하려면 --confirm-cost를 추가하세요.")
        return 2

    results = asyncio.run(
        run_cases(cases, args.model),
        loop_factory=(
            (lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
            if sys.platform == "win32"
            else None
        ),
    )
    summary = summarize(results)
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n문제가 있던 케이스:")
    for result in results:
        if not result["expansion_ok"] or not result["live_ok"] or result["noise_collected"]:
            print(
                f"  {result['id']} ({result['kind']}): "
                f"놓침={result['expansion_missed']} "
                f"실시간={result['live_called']}(기대 {result['expect_live']}) "
                f"잡음={result['noise_collected']}"
            )
    (ROOT / "last_run.json").write_text(
        json.dumps(
            {"model": args.model, "summary": summary, "results": results},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
