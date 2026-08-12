"""모델별 개인 Wiki Build를 직접 실행하고 토큰·지연·비용을 측정한다.

Worker Batch 경로(run_personal_wiki_batch → run_job_batch)는 AsyncConnectionPool을
쓰는데, 이 로컬 환경(Windows + SelectorEventLoop + asyncio.Runner)에서는 풀 연결의
커밋이 유실돼 아무것도 persist되지 않았다(claim조차 queued로 되돌아옴). 그래서 이 스크립트는
배치/풀 기계를 우회하고 빌드 오케스트레이션(build_incremental_wiki)을 **plain
AsyncConnection**으로 직접 호출한다 — ingest 스크립트와 같은 연결 방식이라 커밋이 정상 반영된다.

또한 run_job_batch가 내부에서 capture_llm_calls()를 중첩으로 열어 외부 캡처를 가리므로,
토큰은 record_llm_call_observation을 monkeypatch해 전역 리스트에 누적한다(컨텍스트 전파와
무관하게 모든 complete_with_usage 호출을 포착). 프로덕션 파일은 수정하지 않고 런타임에서만
함수 속성을 교체한다.

실행:
  uv run python scripts/model_wiki_eval/build_model_wiki.py \
      --user-id model-eval-4o-mini --model gpt-4o-mini --out results/4o-mini.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from psycopg import AsyncConnection
from psycopg.rows import dict_row

import agent.llm.features.client as llm_client
from app.config import load_settings
from infrastructure.persistence.api import set_personal_wiki_scope
from agent.wiki_builder.api import build_incremental_wiki

type DictRow = dict[str, Any]

# 1M 토큰당 USD 단가 (2026-08 기준, 기존 llm-model-eval-wiki-report.md와 대조 확인)
# gpt-5는 이번 비교에서 계정 크레딧 문제로 제외했다(docs 참고).
PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1-mini": (0.40, 1.60),
}

# monkeypatch로 채우는 전역 LLM 호출 관측 버퍼: (model, input_tokens, output_tokens)
_TOKEN_LOG: list[tuple[str, int, int]] = []


def _install_usage_hook() -> Any:
    """record_llm_call_observation을 감싸 모든 LLM 호출 토큰을 전역 버퍼에 누적한다."""
    original = llm_client.record_llm_call_observation

    def patched(*, model: str, input_tokens: int, output_tokens: int, value: object) -> None:
        _TOKEN_LOG.append((model, int(input_tokens), int(output_tokens)))
        return original(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            value=value,
        )

    llm_client.record_llm_call_observation = patched  # type: ignore[assignment]
    return original


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """모델 단가표로 입력·출력 토큰의 예상 비용(USD)을 계산한다."""
    input_rate, output_rate = PRICING.get(model, (0.0, 0.0))
    return input_tokens / 1_000_000 * input_rate + output_tokens / 1_000_000 * output_rate


async def fetch_jobs(
    connection: AsyncConnection[DictRow],
    user_id: str,
    sample_urls: set[str] | None = None,
) -> list[tuple[str, str]]:
    """사용자의 personal_wiki_build Job을 (job_id, source_version_id) 목록으로 조회한다.

    sample_urls가 주어지면 원본 문서 canonical_url이 그 집합에 있는 Job만 남긴다
    (대표 샘플만 빌드할 때 사용).
    """
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        cursor = await connection.execute(
            """
            SELECT j.id::text AS id,
                   j.payload->>'source_document_version_id' AS ver,
                   d.canonical_url AS url
            FROM agent.agent_jobs j
            LEFT JOIN agent.user_source_document_versions v
                ON v.id = (j.payload->>'source_document_version_id')::uuid
            LEFT JOIN agent.user_source_documents d
                ON d.id = v.source_document_id
            WHERE j.user_id = %s AND j.job_type = 'personal_wiki_build'
            ORDER BY j.created_at ASC
            """,
            (user_id,),
        )
        rows = await cursor.fetchall()
    jobs = [(row["id"], row["ver"], row["url"]) for row in rows if row["ver"]]
    if sample_urls is not None:
        jobs = [(jid, ver, url) for jid, ver, url in jobs if url in sample_urls]
    return [(jid, ver) for jid, ver, _ in jobs]


async def connect(database_url: str) -> AsyncConnection[DictRow]:
    """Agent DB에 새 연결을 연다."""
    return await AsyncConnection.connect(database_url, row_factory=dict_row)


async def build_one_doc(
    database_url: str, *, user_id: str, version_id: str, job_id: str, model: str
) -> None:
    """문서 하나를 새 연결로 빌드한다. 연결이 끊기면 재연결해 재시도한다(로컬 DB 재시작 대비)."""
    last_error: Exception | None = None
    for attempt in range(3):
        connection = await connect(database_url)
        try:
            await build_incremental_wiki(
                connection,
                user_id=user_id,
                source_document_version_id=version_id,
                job_id=job_id,
                model=model,
            )
            return
        except Exception as error:  # noqa: BLE001 - 연결 오류만 재시도
            last_error = error
            message = str(error).lower()
            transient = any(
                token in message
                for token in ("connection", "server closed", "consuming input", "10053")
            )
            if not transient or attempt == 2:
                raise
            await asyncio.sleep(3.0 * (attempt + 1))
        finally:
            try:
                await connection.close()
            except Exception:  # noqa: BLE001
                pass
    if last_error is not None:
        raise last_error


async def build_all(
    *,
    database_url: str,
    user_id: str,
    model: str,
    max_docs: int | None,
    sample_urls: set[str] | None = None,
) -> dict[str, Any]:
    """모든 대기 문서를 build_incremental_wiki로 직접 순차 빌드하며 측정값을 모은다.

    문서마다 새 연결을 쓴다 — 로컬 agent-db가 부하로 재시작돼 연결이 끊겨도
    한 문서 실패로 격리되고 다음 문서는 새 연결로 이어간다(단일 연결 재사용 시
    한 번 끊기면 나머지가 연쇄 실패하던 문제 해결).
    """
    completed = 0
    failed = 0
    errors: list[dict[str, str]] = []
    per_doc_seconds: list[float] = []
    started = time.monotonic()

    fetch_connection = await connect(database_url)
    try:
        jobs = await fetch_jobs(fetch_connection, user_id, sample_urls)
    finally:
        await fetch_connection.close()

    total = len(jobs) if max_docs is None else min(len(jobs), max_docs)
    print(f"[{model}] 빌드 대상 {total}건 (전체 큐 {len(jobs)}건)", flush=True)
    for index, (job_id, version_id) in enumerate(jobs, start=1):
        if max_docs is not None and index > max_docs:
            break
        doc_started = time.monotonic()
        try:
            await build_one_doc(
                database_url,
                user_id=user_id,
                version_id=version_id,
                job_id=job_id,
                model=model,
            )
            completed += 1
        except Exception as error:  # noqa: BLE001 - 개별 실패는 격리하고 계속
            failed += 1
            errors.append({"version_id": version_id, "error": str(error)[:400]})
        per_doc_seconds.append(time.monotonic() - doc_started)
        if index % 10 == 0 or index <= 2:
            elapsed = time.monotonic() - started
            print(
                f"[{model}] {index}/{total} · 경과 {elapsed:.0f}s "
                f"({elapsed / index:.1f}s/건) · 완료 {completed} 실패 {failed}",
                flush=True,
            )
    wall_seconds = time.monotonic() - started

    by_model: dict[str, dict[str, int]] = defaultdict(
        lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    )
    for call_model, in_tok, out_tok in _TOKEN_LOG:
        bucket = by_model[call_model]
        bucket["calls"] += 1
        bucket["input_tokens"] += in_tok
        bucket["output_tokens"] += out_tok

    eval_bucket = by_model.get(model, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
    cost = estimate_cost(model, eval_bucket["input_tokens"], eval_bucket["output_tokens"])
    processed = completed + failed

    return {
        "model": model,
        "user_id": user_id,
        "documents_processed": processed,
        "completed": completed,
        "failed": failed,
        "wall_seconds": round(wall_seconds, 1),
        "seconds_per_doc": round(wall_seconds / max(processed, 1), 2),
        "llm_calls": eval_bucket["calls"],
        "llm_calls_per_doc": round(eval_bucket["calls"] / max(processed, 1), 2),
        "input_tokens": eval_bucket["input_tokens"],
        "output_tokens": eval_bucket["output_tokens"],
        "estimated_cost_usd": round(cost, 4),
        "cost_per_doc_usd": round(cost / max(processed, 1), 5),
        "tokens_by_model": dict(by_model),
        "errors": errors,
    }


def main() -> int:
    """CLI 인자를 해석하고 모델별 직접 Wiki Build를 실행한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--model", required=True, help="위키 빌드에 쓸 LLM 모델")
    parser.add_argument("--out", type=Path, help="결과 JSON 저장 경로")
    parser.add_argument("--max-docs", type=int, help="스모크 테스트용: 이 건수까지만 처리")
    parser.add_argument(
        "--sample-urls",
        type=Path,
        help="이 파일에 나열된 URL의 문서만 빌드(대표 샘플)",
    )
    args = parser.parse_args()

    settings = load_settings()
    if not settings.agent_database_url:
        print("AGENT_DATABASE_URL이 설정되지 않았습니다.", file=sys.stderr)
        return 2

    sample_urls: set[str] | None = None
    if args.sample_urls:
        sample_urls = {
            line.strip()
            for line in args.sample_urls.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        print(f"샘플 URL {len(sample_urls)}건으로 제한")

    _install_usage_hook()

    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        summary = runner.run(
            build_all(
                database_url=settings.agent_database_url,
                user_id=args.user_id,
                model=args.model,
                max_docs=args.max_docs,
                sample_urls=sample_urls,
            )
        )

    view = {k: v for k, v in summary.items() if k != "errors"}
    print(json.dumps(view, ensure_ascii=False, indent=2))
    if summary["errors"]:
        print(f"\n실패 {len(summary['errors'])}건 예시:")
        for item in summary["errors"][:5]:
            print(f"  - {item['version_id']}: {item['error']}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n결과 저장: {args.out}")

    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
