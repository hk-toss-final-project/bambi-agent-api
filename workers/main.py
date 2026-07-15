"""Agent Worker 프로세스의 명령행 실행 진입점."""

from __future__ import annotations

import argparse
import asyncio
import json
import selectors
import socket
import sys

from app.config import load_settings
from workers.api import run_personal_wiki_batch


def _parse_args() -> argparse.Namespace:
    """Personal Wiki Worker 명령행 옵션을 파싱한다."""
    parser = argparse.ArgumentParser(description="Bambi Agent Worker")
    parser.add_argument(
        "--worker",
        choices=["personal-wiki"],
        default="personal-wiki",
        help="실행할 Worker 유형",
    )
    parser.add_argument("--worker-id", help="Job Lease 소유자 식별자")
    parser.add_argument("--limit", type=int, help="한 번에 Claim할 Job 개수")
    parser.add_argument("--lease-seconds", type=int, help="Job Lease 유지 시간")
    parser.add_argument("--model", help="Personal Wiki 분류 LLM 모델")
    parser.add_argument("--embedding-model", help="Wiki Chunk Embedding 모델")
    return parser.parse_args()


async def _run() -> list[dict[str, object]]:
    """설정과 명령행 옵션으로 Personal Wiki Job Batch 한 번을 실행한다."""
    args = _parse_args()
    settings = load_settings()
    if not settings.agent_database_url:
        raise RuntimeError("AGENT_DATABASE_URL이 필요합니다.")
    worker_id = args.worker_id or f"{socket.gethostname()}-personal-wiki"
    return await run_personal_wiki_batch(
        database_url=settings.agent_database_url,
        worker_id=worker_id,
        limit=args.limit or settings.personal_wiki_worker_batch_size,
        lease_seconds=(
            args.lease_seconds or settings.personal_wiki_job_lease_seconds
        ),
        model=args.model or settings.wiki_llm_model,
        embedding_model=args.embedding_model or settings.wiki_embedding_model,
    )


def main() -> None:
    """Personal Wiki Worker Batch를 실행하고 JSON 결과를 표준 출력한다."""
    # psycopg async 모드는 Windows 기본 ProactorEventLoop를 지원하지 않는다.
    loop_factory = (
        (lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
        if sys.platform == "win32"
        else None
    )
    results = asyncio.run(_run(), loop_factory=loop_factory)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
