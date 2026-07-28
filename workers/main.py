"""Agent Worker 프로세스의 명령행 실행 진입점."""

from __future__ import annotations

import argparse
import asyncio
import json
import selectors
import socket
import sys

from app.config import Settings, load_settings
from workers.api import (
    run_global_content_fetch_batch,
    worker_001,
    worker_002,
    worker_003,
)
from workers.runtime.api import wc_001


def _parse_args() -> argparse.Namespace:
    """Agent Worker 명령행 옵션을 파싱한다."""
    parser = argparse.ArgumentParser(description="Report Builder Agent Worker")
    parser.add_argument(
        "--worker",
        choices=[
            "personal-wiki",
            "report-generation",
            "global-collector",
            "global-content",
        ],
        default="personal-wiki",
        help="실행할 Worker 유형",
    )
    parser.add_argument("--worker-id", help="Job Lease 소유자 식별자")
    parser.add_argument("--limit", type=int, help="한 번에 Claim할 Job 개수")
    parser.add_argument(
        "--keywords",
        help="global-collector 전용: 쉼표로 구분한 수집 키워드",
    )
    parser.add_argument(
        "--providers",
        # google_news는 기본에서 제외한다. 검색 정확도는 Naver보다 낫지만
        # (2026-07-28 실측: 'Cloudflare' 수집 5건 모두 관련 기사 vs Naver 10건 중 3건)
        # 기사 link가 Google 리다이렉트 주소라 **본문을 확보할 수 없다.**
        # Jina Reader가 news.google.com URL에서 403을 반환해, 이 Provider로 수집한
        # 111건이 전부 본문 없는 껍데기로 남았다.
        #
        # 리다이렉트는 HTTP로 풀리지 않는다. follow_redirects로도 news.google.com에
        # 머물고, 응답 HTML에도 원본 링크가 없다(JS로 이동시키는 방식). RSS의
        # <source url>은 언론사 **홈페이지** 주소라 기사 본문을 가리키지 않는다.
        #
        # 본문 없는 문서는 청크가 없어 풀 검색(prag_003)에 걸리지도 않으므로
        # 수집해도 이득이 없다. 원본 URL을 얻는 방법을 찾으면 다시 넣는다.
        default="gdelt,naver",
        help="global-collector 전용: 쉼표로 구분한 수집 Provider (기본 gdelt,naver)",
    )
    parser.add_argument(
        "--limit-per-provider",
        type=int,
        default=10,
        help="global-collector 전용: Provider당 최대 수집 기사 수",
    )
    parser.add_argument(
        "--language",
        help="global-collector 전용: 검색 언어 힌트 (예: ko)",
    )
    parser.add_argument(
        "--model",
        help="Worker LLM 모델 (기본: Wiki는 WIKI_LLM_MODEL, Report Builder는 REPORT_LLM_MODEL)",
    )
    parser.add_argument("--lease-seconds", type=int, help="Job Lease 유지 시간")
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Batch를 상주 모드로 반복 실행 (scheduled_at이 된 Job만 Claim)",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=60,
        help="상주 모드에서 처리할 Job이 없을 때 다음 확인까지 대기 초",
    )
    return parser.parse_args()


async def _run_batch_once(
    args: argparse.Namespace, settings: Settings, worker_id: str
) -> list[dict[str, object]]:
    """설정과 명령행 옵션으로 선택한 Worker의 Job Batch 한 번을 실행한다."""
    if args.worker == "global-collector":
        keywords = [
            keyword.strip()
            for keyword in (args.keywords or "").split(",")
            if keyword.strip()
        ]
        if not keywords:
            raise RuntimeError("global-collector는 --keywords가 필요합니다.")
        providers = [
            name.strip() for name in args.providers.split(",") if name.strip()
        ]
        naver_secret = (
            settings.naver_client_secret.get_secret_value()
            if settings.naver_client_secret
            else None
        )
        return await worker_001(
            database_url=settings.agent_database_url,
            keywords=keywords,
            providers=providers,
            limit_per_provider=args.limit_per_provider,
            language=args.language,
            naver_client_id=settings.naver_client_id,
            naver_client_secret=naver_secret,
            gdelt_base_url=settings.gdelt_base_url,
        )
    if args.worker == "global-content":
        return await run_global_content_fetch_batch(
            database_url=settings.agent_database_url,
            limit=args.limit or settings.personal_wiki_worker_batch_size,
        )
    if args.worker == "report-generation":
        return await worker_003(
            database_url=settings.agent_database_url,
            worker_id=worker_id,
            limit=args.limit or settings.personal_wiki_worker_batch_size,
            lease_seconds=(
                args.lease_seconds or settings.personal_wiki_job_lease_seconds
            ),
            model=args.model or settings.report_llm_model,
        )
    return await worker_002(
        database_url=settings.agent_database_url,
        worker_id=worker_id,
        limit=args.limit or settings.personal_wiki_worker_batch_size,
        lease_seconds=(
            args.lease_seconds or settings.personal_wiki_job_lease_seconds
        ),
        model=args.model or settings.wiki_llm_model,
    )


async def _run() -> None:
    """단발 또는 상주 모드로 선택한 Agent Worker를 실행한다.

    상주 모드는 WC-001 Queue Job Consume 루프에 위임한다. 실행 가능한
    Job(scheduled_at <= now)이 있으면 연속으로 Batch를 소진하고, 없으면
    interval-seconds 동안 대기 후 다시 확인한다. 조용 시간 정책(SCH-009)이
    미뤄 둔 Job은 그 시각이 되기 전에는 Claim되지 않는다.
    """
    args = _parse_args()
    settings = load_settings()
    if not settings.agent_database_url:
        raise RuntimeError("AGENT_DATABASE_URL이 필요합니다.")
    worker_id = args.worker_id or f"{socket.gethostname()}-{args.worker}"
    if args.loop and args.worker in ("global-collector", "global-content"):
        raise RuntimeError(
            f"{args.worker} Worker는 상주 --loop 모드를 지원하지 않습니다. "
            "정기 수집은 Scheduler로 Batch를 반복 실행하세요."
        )
    if not args.loop:
        results = await _run_batch_once(args, settings, worker_id)
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
        return

    def on_batch(results: list[dict[str, object]]) -> None:
        """결과가 있는 Batch를 JSON Line으로 출력한다."""
        print(json.dumps(results, ensure_ascii=False, default=str), flush=True)

    if args.worker == "report-generation":
        await wc_001(
            database_url=settings.agent_database_url,
            worker_id=worker_id,
            limit=args.limit or settings.personal_wiki_worker_batch_size,
            lease_seconds=(
                args.lease_seconds or settings.personal_wiki_job_lease_seconds
            ),
            model=args.model or settings.report_llm_model,
            interval_seconds=args.interval_seconds,
            max_batches=None,
            job_type="report_generation",
            on_batch=on_batch,
        )
        return
    await wc_001(
        database_url=settings.agent_database_url,
        worker_id=worker_id,
        limit=args.limit or settings.personal_wiki_worker_batch_size,
        lease_seconds=(args.lease_seconds or settings.personal_wiki_job_lease_seconds),
        model=args.model or settings.wiki_llm_model,
        interval_seconds=args.interval_seconds,
        max_batches=None,
        job_type="personal_wiki_build",
        on_batch=on_batch,
    )


def main() -> None:
    """선택한 Agent Worker를 실행하고 JSON 결과를 표준 출력한다."""
    # psycopg async 모드는 Windows 기본 ProactorEventLoop를 지원하지 않는다.
    loop_factory = (
        (lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
        if sys.platform == "win32"
        else None
    )
    try:
        asyncio.run(_run(), loop_factory=loop_factory)
    except KeyboardInterrupt:
        print("Worker를 종료합니다.", file=sys.stderr)


if __name__ == "__main__":
    main()
