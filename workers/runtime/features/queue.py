"""기능 구현 모듈.

WC-001, WC-002 기능의 실제 구현 위치를 제공한다.

WC-001은 실행 가능한 Job Batch를 설정된 크기만큼 반복해서 가져오는 상주
소비 루프다. Personal Wiki Build와 Bambi Generation이 같은 루프 규칙을
사용한다. Job Claim 자체(WC-002)와 조용 시간 정책(SCH-009)은
scheduled_at <= now 조건을 통해 Claim SQL이 존중하므로, 이 루프는
실행 시각이 되지 않은 Job을 가져오지 않는다.
"""

import sys
import traceback
from asyncio import sleep
from collections.abc import Awaitable, Callable

from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation
from workers.api import run_bambi_generation_batch, run_personal_wiki_batch

type BatchResults = list[dict[str, object]]
type BatchRunner = Callable[..., Awaitable[BatchResults]]
type BatchObserver = Callable[[BatchResults], None]


async def _consume_job_batches(
    *,
    batch_runner: BatchRunner,
    runner_kwargs: dict[str, object],
    interval_seconds: int,
    max_batches: int | None,
    on_batch: BatchObserver | None,
) -> BatchResults:
    """Batch 실행기를 WC-001 규칙으로 반복 호출하는 공통 소비 루프.

    Batch에 결과가 있으면 남은 Job을 소진하기 위해 즉시 다음 Batch를
    가져오고, 없으면 interval_seconds 동안 대기한 뒤 다시 확인한다.
    max_batches가 None이면 상주 모드로 계속 실행하고, 정수면 그 횟수의
    Batch만 가져온 뒤 누적 결과를 반환한다.
    """
    if max_batches is not None and max_batches < 1:
        raise ValueError("WC-001의 max_batches는 1 이상이거나 None이어야 합니다.")
    if interval_seconds < 0:
        raise ValueError("WC-001의 interval_seconds는 0 이상이어야 합니다.")
    consumed: BatchResults = []
    batches = 0
    while True:
        try:
            results = await batch_runner(**runner_kwargs)
        except Exception:
            # 상주 Worker는 Batch 하나의 예외로 죽지 않고 기록 후 계속한다.
            traceback.print_exc(file=sys.stderr)
            results = []
        batches += 1
        if results and on_batch is not None:
            on_batch(results)
        if max_batches is not None:
            consumed.extend(results)
            if batches >= max_batches:
                return consumed
        if not results:
            await sleep(interval_seconds)


async def consume_personal_wiki_jobs(
    *,
    database_url: str,
    worker_id: str,
    limit: int,
    lease_seconds: int,
    model: str,
    interval_seconds: int = 60,
    max_batches: int | None = None,
    batch_runner: BatchRunner = run_personal_wiki_batch,
    on_batch: BatchObserver | None = None,
) -> BatchResults:
    """실행 가능한 Personal Wiki Job Batch를 반복해서 가져와 처리한다.

    Args:
        database_url: Agent DB 연결 문자열
        worker_id: Job Lease 소유자 식별자
        limit: Batch 하나가 Claim할 최대 Job 수 (WC-001 Batch 크기)
        lease_seconds: Job Lease 유지 시간(초)
        model: Personal Wiki 분류 LLM 모델
        interval_seconds: 처리할 Job이 없을 때 다음 확인까지 대기 초
        max_batches: 가져올 Batch 횟수 상한. None이면 무제한 상주
        batch_runner: Batch 한 번을 실행하는 함수 (테스트 대체용)
        on_batch: 결과가 있는 Batch마다 호출할 관찰자 (로그 출력용)

    Returns:
        max_batches 상한 안에서 처리한 Job 결과 누적 목록.
        상주 모드에서는 메모리 누적을 피하기 위해 빈 목록을 유지한다.
    """
    return await _consume_job_batches(
        batch_runner=batch_runner,
        runner_kwargs={
            "database_url": database_url,
            "worker_id": worker_id,
            "limit": limit,
            "lease_seconds": lease_seconds,
            "model": model,
        },
        interval_seconds=interval_seconds,
        max_batches=max_batches,
        on_batch=on_batch,
    )


async def consume_bambi_generation_jobs(
    *,
    database_url: str,
    worker_id: str,
    limit: int,
    lease_seconds: int,
    model: str,
    interval_seconds: int = 60,
    max_batches: int | None = None,
    batch_runner: BatchRunner = run_bambi_generation_batch,
    on_batch: BatchObserver | None = None,
) -> BatchResults:
    """실행 가능한 Bambi Generation Job Batch를 반복해서 가져와 처리한다.

    소비 규칙은 consume_personal_wiki_jobs와 같으며, Batch 실행기만
    Bambi Generation Worker를 사용한다.

    Args:
        database_url: Agent DB 연결 문자열
        worker_id: Job Lease 소유자 식별자
        limit: Batch 하나가 Claim할 최대 Job 수 (WC-001 Batch 크기)
        lease_seconds: Job Lease 유지 시간(초)
        model: Bambi 콘텐츠 생성 LLM 모델
        interval_seconds: 처리할 Job이 없을 때 다음 확인까지 대기 초
        max_batches: 가져올 Batch 횟수 상한. None이면 무제한 상주
        batch_runner: Batch 한 번을 실행하는 함수 (테스트 대체용)
        on_batch: 결과가 있는 Batch마다 호출할 관찰자 (로그 출력용)

    Returns:
        max_batches 상한 안에서 처리한 Job 결과 누적 목록.
        상주 모드에서는 메모리 누적을 피하기 위해 빈 목록을 유지한다.
    """
    return await _consume_job_batches(
        batch_runner=batch_runner,
        runner_kwargs={
            "database_url": database_url,
            "worker_id": worker_id,
            "limit": limit,
            "lease_seconds": lease_seconds,
            "model": model,
        },
        interval_seconds=interval_seconds,
        max_batches=max_batches,
        on_batch=on_batch,
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wc_001(request: FeatureRequest) -> FeatureResult:
    """[WC-001] Queue Job Consume.

    설정된 Batch 크기만큼 실행 가능한 Personal Wiki 작업을 가져온다.
    max_batches 횟수만큼 Batch를 소비하고 처리 결과를 반환한다.
    """
    database_url = request.payload.get("database_url")
    worker_id = request.payload.get("worker_id", request.actor_id or "personal-wiki-worker")
    limit = request.payload.get("limit", 1)
    lease_seconds = request.payload.get("lease_seconds", 600)
    model = request.payload.get("model", "gpt-4.1-mini")
    interval_seconds = request.payload.get("interval_seconds", 0)
    max_batches = request.payload.get("max_batches", 1)
    job_type = request.payload.get("job_type", "personal_wiki_build")
    on_batch = request.payload.get("on_batch")
    if not isinstance(database_url, str) or not database_url:
        raise ValueError("WC-001에 database_url이 필요합니다.")
    if not isinstance(worker_id, str) or not worker_id:
        raise ValueError("WC-001에 worker_id가 필요합니다.")
    if not isinstance(limit, int) or not isinstance(lease_seconds, int):
        raise ValueError("WC-001의 limit과 lease_seconds는 정수여야 합니다.")
    if not isinstance(interval_seconds, int):
        raise ValueError("WC-001의 interval_seconds는 정수여야 합니다.")
    if max_batches is not None and not isinstance(max_batches, int):
        raise ValueError("WC-001의 max_batches는 정수 또는 None이어야 합니다.")
    if not isinstance(model, str) or not model:
        raise ValueError("WC-001의 model은 빈 문자열이면 안 됩니다.")
    if job_type not in ("personal_wiki_build", "bambi_generation"):
        raise ValueError("WC-001이 지원하지 않는 job_type입니다.")
    if on_batch is not None and not callable(on_batch):
        raise ValueError("WC-001의 on_batch는 호출 가능해야 합니다.")
    consumer = (
        consume_bambi_generation_jobs
        if job_type == "bambi_generation"
        else consume_personal_wiki_jobs
    )
    results = await consumer(
        database_url=database_url,
        worker_id=worker_id,
        limit=limit,
        lease_seconds=lease_seconds,
        model=model,
        interval_seconds=interval_seconds,
        max_batches=max_batches,
        on_batch=on_batch,  # type: ignore[arg-type]
    )
    return FeatureResult(
        feature_id="WC-001",
        data={"batches": max_batches, "processed": len(results), "results": results},
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wc_002(request: FeatureRequest) -> FeatureResult:
    """[WC-002] Job Claim.

    하나의 Worker가 작업을 점유한다.
    """
    return await execute_feature_implementation(request, feature_id="WC-002")
