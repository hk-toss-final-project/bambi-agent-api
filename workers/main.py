"""Agent Worker 프로세스의 명령행 실행 진입점."""

from __future__ import annotations

import argparse
import asyncio
import json
import selectors
import socket
import sys

from app.config import Settings, load_settings
from app.logging_config import configure_logging
from workers.api import (
    consume_openai_batches,
    run_global_content_fetch_batch,
    run_briefing_preparation_batch,
    run_url_collection_batch,
    run_openai_batch_cycle,
    worker_001,
    worker_002,
    worker_003,
)
from workers.runtime.api import ProviderRateLimitPolicy, wc_001

DEFAULT_WORKER_INTERVAL_SECONDS = 60
INTERACTIVE_WORKER_INTERVAL_SECONDS = 5


def _openai_rate_policy(
    settings: Settings,
    *,
    model: str,
    estimated_requests: int,
    estimated_tokens: int,
) -> ProviderRateLimitPolicy:
    """환경 설정을 Worker Job의 OpenAI 모델별 예약 정책으로 변환한다."""
    return ProviderRateLimitPolicy(
        provider="openai",
        resource_key=model,
        estimated_requests=estimated_requests,
        estimated_tokens=estimated_tokens,
        default_rpm=settings.openai_default_rpm,
        default_tpm=settings.openai_default_tpm,
    )


def _parse_args() -> argparse.Namespace:
    """Agent Worker 명령행 옵션을 파싱한다."""
    parser = argparse.ArgumentParser(description="Report Builder Agent Worker")
    parser.add_argument(
        "--worker",
        choices=[
            "personal-wiki",
            "url-collection",
            "report-generation",
            "briefing-preparation",
            "global-collector",
            "global-content",
            "openai-batch",
        ],
        default="personal-wiki",
        help="실행할 Worker 유형",
    )
    parser.add_argument("--worker-id", help="Job Lease 소유자 식별자")
    parser.add_argument("--limit", type=int, help="한 번에 Claim할 Job 개수")
    parser.add_argument(
        "--concurrency",
        type=int,
        help="Claim 크기와 별개인 실제 Job 동시 실행 수",
    )
    parser.add_argument(
        "--keywords",
        help="global-collector 전용: 쉼표로 구분한 수집 키워드",
    )
    parser.add_argument(
        "--providers",
        # google_news를 기본에 포함한다. Naver는 한국어 키워드에 강하지만 영문
        # 고유명사를 잘 찾지 못한다(2026-07-28 실측: 'Cloudflare' 수집 10건 중 관련
        # 3건, google_news는 5건 전부 관련). 두 소스가 서로의 약점을 메운다.
        #
        # 이 Provider는 한 번 철회했다가 되살렸다. 기사 link가 Google 리다이렉트
        # 주소라 본문 확보가 전부 실패했었는데(JINA_HTTP_403, 111건 전원),
        # googlenewsdecoder로 원본 URL을 복원해 해결했다. 디코딩에 실패한 기사는
        # 수집 단계에서 제외하므로 본문 없는 문서가 풀에 쌓이지 않는다.
        default="gdelt,naver,google_news",
        help=(
            "global-collector 전용: 쉼표로 구분한 수집 Provider "
            "(기본 gdelt,naver,google_news)"
        ),
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
        help=(
            "상주 모드에서 처리할 Job이 없을 때 다음 확인까지 대기 초 "
            "(기본: Wiki·URL 5초, 나머지 60초)"
        ),
    )
    return parser.parse_args()


def _worker_interval_seconds(args: argparse.Namespace) -> int:
    """Worker 종류와 명시 옵션으로 빈 Queue 재조회 간격을 결정한다."""
    configured = getattr(args, "interval_seconds", None)
    if configured is not None:
        return int(configured)
    if args.worker in ("personal-wiki", "url-collection"):
        return INTERACTIVE_WORKER_INTERVAL_SECONDS
    return DEFAULT_WORKER_INTERVAL_SECONDS


async def _run_batch_once(
    args: argparse.Namespace, settings: Settings, worker_id: str
) -> list[dict[str, object]]:
    """설정과 명령행 옵션으로 선택한 Worker의 Job Batch 한 번을 실행한다."""
    if args.worker == "openai-batch":
        if settings.openai_api_key is None:
            raise RuntimeError("openai-batch Worker에 OPENAI_API_KEY가 필요합니다.")
        return await run_openai_batch_cycle(
            database_url=settings.agent_database_url,
            api_key=settings.openai_api_key.get_secret_value(),
            max_items=settings.openai_batch_max_items,
            max_submissions=settings.openai_batch_max_submissions,
            poll_limit=settings.openai_batch_poll_limit,
            poll_interval_seconds=settings.openai_batch_poll_interval_seconds,
            poll_lease_seconds=settings.openai_batch_poll_lease_seconds,
            worker_id=worker_id,
        )
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
        news_api_key = (
            settings.news_api_key.get_secret_value()
            if settings.news_api_key
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
            news_api_key=news_api_key,
        )
    if args.worker == "global-content":
        return await run_global_content_fetch_batch(
            database_url=settings.agent_database_url,
            limit=args.limit or settings.personal_wiki_worker_batch_size,
        )
    if args.worker == "url-collection":
        return await run_url_collection_batch(
            database_url=settings.agent_database_url,
            worker_id=worker_id,
            limit=args.limit or settings.url_collection_worker_batch_size,
            concurrency=(
                args.concurrency or settings.url_collection_job_concurrency
            ),
            lease_seconds=(
                args.lease_seconds or settings.personal_wiki_job_lease_seconds
            ),
        )
    if args.worker == "report-generation":
        model = args.model or settings.report_llm_model
        return await worker_003(
            database_url=settings.agent_database_url,
            worker_id=worker_id,
            limit=args.limit or settings.report_worker_batch_size,
            concurrency=args.concurrency or settings.report_job_concurrency,
            lease_seconds=(
                args.lease_seconds or settings.personal_wiki_job_lease_seconds
            ),
            model=model,
            rate_limit_policy=_openai_rate_policy(
                settings,
                model=model,
                estimated_requests=settings.report_openai_requests_per_job,
                estimated_tokens=settings.report_openai_tokens_per_job,
            ),
        )
    if args.worker == "briefing-preparation":
        model = args.model or settings.report_llm_model
        return await run_briefing_preparation_batch(
            database_url=settings.agent_database_url,
            worker_id=worker_id,
            limit=args.limit or settings.briefing_worker_batch_size,
            concurrency=args.concurrency or settings.briefing_job_concurrency,
            lease_seconds=(
                args.lease_seconds or settings.personal_wiki_job_lease_seconds
            ),
            model=model,
            rate_limit_policy=_openai_rate_policy(
                settings,
                model=model,
                estimated_requests=settings.briefing_openai_requests_per_job,
                estimated_tokens=settings.briefing_openai_tokens_per_job,
            ),
        )
    model = args.model or settings.wiki_llm_model
    return await worker_002(
        database_url=settings.agent_database_url,
        worker_id=worker_id,
        limit=args.limit or settings.personal_wiki_worker_batch_size,
        concurrency=args.concurrency or settings.personal_wiki_job_concurrency,
        lease_seconds=(
            args.lease_seconds or settings.personal_wiki_job_lease_seconds
        ),
        model=model,
        rate_limit_policy=_openai_rate_policy(
            settings,
            model=model,
            estimated_requests=settings.wiki_openai_requests_per_job,
            estimated_tokens=settings.wiki_openai_tokens_per_job,
        ),
        embedding_model=settings.wiki_embedding_model,
        embedding_batch_threshold=settings.wiki_embedding_batch_threshold,
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
    interval_seconds = _worker_interval_seconds(args)
    # Worker는 FastAPI 앱을 만들지 않으므로 로깅을 여기서 직접 구성한다. 없으면
    # root에 핸들러가 없어 agent.*·workers.* 로거 출력이 통째로 버려진다
    # (2026-08-05 실측: 배포 Worker stdout에 logger 라인 0건. print만 보였다).
    # 진단이 필요한 순간에 가장 먼저 아쉬운 것이 이 로그다.
    configure_logging(
        log_level=settings.log_level, log_directory=settings.log_directory
    )
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

    if args.worker == "openai-batch":
        if settings.openai_api_key is None:
            raise RuntimeError("openai-batch Worker에 OPENAI_API_KEY가 필요합니다.")
        await consume_openai_batches(
            database_url=settings.agent_database_url,
            api_key=settings.openai_api_key.get_secret_value(),
            interval_seconds=interval_seconds,
            max_cycles=None,
            max_items=settings.openai_batch_max_items,
            max_submissions=settings.openai_batch_max_submissions,
            poll_limit=settings.openai_batch_poll_limit,
            poll_interval_seconds=settings.openai_batch_poll_interval_seconds,
            poll_lease_seconds=settings.openai_batch_poll_lease_seconds,
            worker_id=worker_id,
            on_cycle=on_batch,
        )
        return

    if args.worker == "report-generation":
        model = args.model or settings.report_llm_model
        await wc_001(
            database_url=settings.agent_database_url,
            worker_id=worker_id,
            limit=args.limit or settings.report_worker_batch_size,
            concurrency=args.concurrency or settings.report_job_concurrency,
            lease_seconds=(
                args.lease_seconds or settings.personal_wiki_job_lease_seconds
            ),
            model=model,
            rate_limit_policy=_openai_rate_policy(
                settings,
                model=model,
                estimated_requests=settings.report_openai_requests_per_job,
                estimated_tokens=settings.report_openai_tokens_per_job,
            ),
            interval_seconds=interval_seconds,
            max_batches=None,
            job_type="report_generation",
            on_batch=on_batch,
        )
        return
    if args.worker == "briefing-preparation":
        model = args.model or settings.report_llm_model
        await wc_001(
            database_url=settings.agent_database_url,
            worker_id=worker_id,
            limit=args.limit or settings.briefing_worker_batch_size,
            concurrency=args.concurrency or settings.briefing_job_concurrency,
            lease_seconds=(
                args.lease_seconds or settings.personal_wiki_job_lease_seconds
            ),
            model=model,
            rate_limit_policy=_openai_rate_policy(
                settings,
                model=model,
                estimated_requests=settings.briefing_openai_requests_per_job,
                estimated_tokens=settings.briefing_openai_tokens_per_job,
            ),
            interval_seconds=interval_seconds,
            max_batches=None,
            job_type="briefing_preparation",
            on_batch=on_batch,
        )
        return
    if args.worker == "url-collection":
        await wc_001(
            database_url=settings.agent_database_url,
            worker_id=worker_id,
            limit=args.limit or settings.url_collection_worker_batch_size,
            concurrency=(
                args.concurrency or settings.url_collection_job_concurrency
            ),
            lease_seconds=(
                args.lease_seconds or settings.personal_wiki_job_lease_seconds
            ),
            interval_seconds=interval_seconds,
            max_batches=None,
            job_type="personal_wiki_url",
            on_batch=on_batch,
        )
        return
    model = args.model or settings.wiki_llm_model
    await wc_001(
        database_url=settings.agent_database_url,
        worker_id=worker_id,
        limit=args.limit or settings.personal_wiki_worker_batch_size,
        concurrency=args.concurrency or settings.personal_wiki_job_concurrency,
        lease_seconds=(args.lease_seconds or settings.personal_wiki_job_lease_seconds),
        model=model,
        rate_limit_policy=_openai_rate_policy(
            settings,
            model=model,
            estimated_requests=settings.wiki_openai_requests_per_job,
            estimated_tokens=settings.wiki_openai_tokens_per_job,
        ),
        embedding_batch_threshold=settings.wiki_embedding_batch_threshold,
        interval_seconds=interval_seconds,
        max_batches=None,
        job_type="personal_wiki_build",
        on_batch=on_batch,
    )


def configure_output_encoding() -> None:
    """콘솔 인코딩과 무관하게 결과 출력이 실패하지 않도록 UTF-8로 맞춘다.

    Windows 기본 콘솔은 cp949라 이모지가 섞인 제목(YouTube 영상 등)을 출력할 때
    UnicodeEncodeError로 프로세스가 종료된다. 수집·저장은 이미 끝난 뒤에 나는
    오류라 데이터는 남지만 종료 코드가 1이 되어 실패한 실행처럼 보인다.

    인코딩을 바꿀 수 없는 스트림(리다이렉트된 바이너리 등)은 그대로 둔다.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            continue


def main() -> None:
    """선택한 Agent Worker를 실행하고 JSON 결과를 표준 출력한다."""
    configure_output_encoding()
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
