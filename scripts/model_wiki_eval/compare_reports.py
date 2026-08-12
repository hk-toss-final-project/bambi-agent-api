"""모델별 개인 Wiki를 근거로 온디맨드 리포트를 생성하고 모델 간 비교한다.

각 주제(topic)에 대해:
  1) 주제를 임베딩하고
  2) 모델별 사용자 Wiki에서 벡터 유사도로 근거 Chunk(top-k)를 검색한 뒤
     (load_personal_wiki_vector_context — 리포트 파이프라인이 실제로 쓰는 검색)
  3) 그 근거로 온디맨드 리포트를 생성한다(generate_report_content).

같은 검색·같은 임베딩 모델을 쓰되 **근거가 되는 Wiki만 모델별로 다르므로**, 리포트 품질 차이는
곧 각 모델이 만든 Wiki의 차이를 반영한다. 지연·토큰·비용과, 검색된 근거 중 실제로 인용된
비율(그라운딩)을 함께 기록한다.

실행:
  uv run python scripts/model_wiki_eval/compare_reports.py --out reports/compare.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from psycopg import AsyncConnection
from psycopg.rows import dict_row

import agent.llm.features.client as llm_client
from agent.report_builder.api import generate_report_content
from agent.wiki_builder.api import generate_relation_query_embeddings
from app.config import load_settings
from infrastructure.persistence.api import (
    load_personal_wiki_vector_context,
    set_personal_wiki_scope,
)

type DictRow = dict[str, Any]

PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1-mini": (0.40, 1.60),
}

EMBEDDING_MODEL = "text-embedding-3-small"

# (표시 이름, user_id, 리포트 LLM 모델) — gpt-5는 계정 크레딧 문제로 이번 비교에서 제외
MODELS = [
    ("gpt-4o-mini", "model-eval-4o-mini", "gpt-4o-mini"),
    ("gpt-4.1-mini", "model-eval-4.1-mini", "gpt-4.1-mini"),
]

# 관심사를 가로지르는 비교 주제
TOPICS = [
    "비트코인 반감기 이후 시세 전망",
    "AI 코딩 에이전트 도구 비교와 선택 기준",
    "다낭 여행 준비물과 추천 일정",
]

_TOKEN_LOG: list[tuple[str, int, int]] = []


def _install_usage_hook() -> None:
    """record_llm_call_observation을 감싸 LLM 호출 토큰을 전역 버퍼에 누적한다."""
    original = llm_client.record_llm_call_observation

    def patched(*, model: str, input_tokens: int, output_tokens: int, value: object) -> None:
        _TOKEN_LOG.append((model, int(input_tokens), int(output_tokens)))
        return original(model=model, input_tokens=input_tokens, output_tokens=output_tokens, value=value)

    llm_client.record_llm_call_observation = patched  # type: ignore[assignment]


def cost_of(model: str, tokens: list[tuple[str, int, int]]) -> tuple[int, int, float]:
    """특정 모델 호출들의 입력·출력 토큰 합과 비용을 계산한다."""
    in_tok = sum(i for m, i, o in tokens if m == model)
    out_tok = sum(o for m, i, o in tokens if m == model)
    ir, orr = PRICING.get(model, (0.0, 0.0))
    return in_tok, out_tok, in_tok / 1e6 * ir + out_tok / 1e6 * orr


async def embed_topic(topic: str) -> list[float]:
    """주제 문장을 검색용 벡터로 임베딩한다."""
    vectors = await asyncio.to_thread(
        generate_relation_query_embeddings, [topic], model=EMBEDDING_MODEL
    )
    return list(vectors[0])


async def run_one(
    database_url: str, *, user_id: str, model: str, topic: str, embedding: list[float], top_k: int
) -> dict[str, Any]:
    """한 모델·한 주제에 대해 근거 검색 + 리포트 생성 결과를 만든다."""
    connection: AsyncConnection[DictRow] = await AsyncConnection.connect(
        database_url, row_factory=dict_row
    )
    try:
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=user_id)
            contexts = await load_personal_wiki_vector_context(
                connection,
                user_id=user_id,
                query_embedding=embedding,
                model_name=EMBEDDING_MODEL,
                top_k=top_k,
            )
    finally:
        await connection.close()

    context_view = [
        {"ref": c.reference, "title": c.title, "url": c.url, "score": round(c.score, 3)}
        for c in contexts
    ]

    before = len(_TOKEN_LOG)
    started = time.monotonic()
    error = None
    report_view: dict[str, Any] = {}
    cited = 0
    if not contexts:
        error = "근거 없음(위키에 관련 노드 없음)"
    else:
        try:
            report = await asyncio.to_thread(
                generate_report_content,
                topic=topic,
                content_type="briefing",
                language="ko",
                contexts=contexts,
                model=model,
            )
            cited = len(report.citation_references)
            report_view = {
                "title": report.title,
                "summary": report.summary,
                "body": report.body,
                "citations": list(report.citation_references),
                "tags": list(report.content_tags),
            }
        except Exception as err:  # noqa: BLE001 - 실패도 비교 결과로 기록
            error = str(err)[:400]
    latency = time.monotonic() - started
    in_tok, out_tok, cost = cost_of(model, _TOKEN_LOG[before:])

    return {
        "model": model,
        "context_count": len(contexts),
        "contexts": context_view,
        "cited_count": cited,
        "grounding_ratio": round(cited / len(contexts), 3) if contexts else 0.0,
        "report": report_view,
        "error": error,
        "latency_s": round(latency, 2),
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost_usd": round(cost, 4),
        "body_chars": len(report_view.get("body", "")),
    }


async def run_all(database_url: str, top_k: int) -> dict[str, Any]:
    """모든 주제·모델 조합의 온디맨드 리포트를 생성해 비교 구조로 모은다."""
    topics_out = []
    for topic in TOPICS:
        print(f"\n=== 주제: {topic} ===", flush=True)
        embedding = await embed_topic(topic)
        model_results = []
        for _, user_id, model in MODELS:
            print(f"  - {model} 생성 중…", flush=True)
            result = await run_one(
                database_url,
                user_id=user_id,
                model=model,
                topic=topic,
                embedding=embedding,
                top_k=top_k,
            )
            print(
                f"    근거 {result['context_count']} · 인용 {result['cited_count']} · "
                f"{result['latency_s']}s · {result['cost_usd']} · "
                f"본문 {result['body_chars']}자"
                + (f" · 오류: {result['error']}" if result["error"] else ""),
                flush=True,
            )
            model_results.append(result)
        topics_out.append({"topic": topic, "models": model_results})
    return {"top_k": top_k, "topics": topics_out}


def render_markdown(result: dict[str, Any]) -> str:
    """같은 주제에 대한 모델별 생성 리포트를 사람이 읽을 수 있는 나란히 비교 문서로 만든다."""
    lines: list[str] = ["# 모델별 온디맨드 리포트 비교\n"]
    lines.append(
        f"검색 top-k: {result['top_k']} · 같은 주제·같은 근거 검색 파이프라인으로 "
        "모델(리포트 생성 LLM)만 바꿔 실행한 결과.\n"
    )
    for entry in result["topics"]:
        topic = entry["topic"]
        lines.append(f"\n## 주제: {topic}\n")
        lines.append("| 모델 | 근거 수 | 인용 수 | 그라운딩 | 지연 | 비용 | 본문 길이 | 상태 |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---|")
        for m in entry["models"]:
            status = "오류" if m["error"] else "성공"
            lines.append(
                f"| {m['model']} | {m['context_count']} | {m['cited_count']} | "
                f"{m['grounding_ratio']*100:.0f}% | {m['latency_s']}s | "
                f"${m['cost_usd']} | {m['body_chars']}자 | {status} |"
            )
        for m in entry["models"]:
            lines.append(f"\n### {m['model']} 생성 결과\n")
            if m["error"]:
                lines.append(f"> 오류: {m['error']}\n")
                continue
            report = m["report"]
            lines.append(f"**{report['title']}**\n")
            lines.append(f"{report['summary']}\n")
            lines.append(report["body"] + "\n")
            if report.get("citations"):
                lines.append(f"인용 참조: {', '.join(report['citations'])}\n")
            if report.get("tags"):
                lines.append(f"태그: {', '.join(report['tags'])}\n")
            lines.append("**검색된 근거 (top-k)**\n")
            for c in m["contexts"]:
                lines.append(f"- `{c['ref']}` ({c['score']}) {c['title']} — {c['url'] or '출처 URL 없음'}")
    return "\n".join(lines)


def main() -> int:
    """CLI 인자를 해석하고 리포트 비교를 실행한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--out-md", type=Path, help="사람이 읽을 나란히 비교 Markdown 저장 경로"
    )
    parser.add_argument("--top-k", type=int, default=8)
    args = parser.parse_args()

    settings = load_settings()
    if not settings.agent_database_url:
        print("AGENT_DATABASE_URL이 설정되지 않았습니다.", file=sys.stderr)
        return 2

    _install_usage_hook()
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        result = runner.run(run_all(settings.agent_database_url, args.top_k))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n비교 저장: {args.out}")

    if args.out_md:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(render_markdown(result), encoding="utf-8")
        print(f"비교 Markdown 저장: {args.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
