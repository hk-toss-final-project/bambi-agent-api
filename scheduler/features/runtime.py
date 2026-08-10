"""수집 Scheduler 런타임.

등록된 Global Source의 수집 주기를 판정하고 실행하는 Scheduler 본체와 상주
루프를 제공한다. CLI 진입점(`scheduler/main.py`)과 API 서버 기동
(`app/main.py`)이 같은 런타임을 공유하도록 진입점에서 분리했다.

tick 하나는 두 단계다. ① 실행 차례가 된 Source를 수집하고(URL만 저장)
② 아직 본문이 비어 있는 문서를 Jina Reader로 채운다. ②가 없으면 풀에 근거로
쓸 수 없는 URL만 쌓이므로 같은 시계 안에서 함께 돌린다.

시계는 프로세스 하나만 돌려야 같은 수집이 중복 실행되지 않는다. API 서버를
여러 인스턴스로 띄우는 배포에서는 서버 내장 Scheduler를
`ENABLE_COLLECTION_SCHEDULER=false`로 끄고 CLI Scheduler를 한 벌만 띄운다.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from functools import partial
from datetime import UTC, datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.config import Settings, load_settings
from infrastructure.persistence.api import (
    ClaimedAgentJob,
    claim_runnable_agent_jobs,
    complete_agent_job,
    fail_agent_job,
    set_system_job_scope,
)
from .collection import (
    SCHEDULED_PROVIDERS,
    CollectionCredentials,
    CollectionScheduleResult,
    run_provider_collection_schedule,
    sch_001,
    sch_002,
    sch_003,
    sch_004,
)
from .management import sch_021
from .wiki import sch_010
from workers.api import run_global_content_fetch_batch

type DictRow = dict[str, Any]

logger = logging.getLogger(__name__)

# Provider 이름과 정기 수집 스케줄 기능의 연결.
#
# 한 tick 안에서 이 순서대로 실행한다. 빠른 Provider를 앞에 둬서, 종료 신호로
# tick이 중간에 끊겨도 값싼 수집은 이미 끝나 있게 한다. google_news는 원본 URL
# 디코딩 때문에 키워드당 12초쯤 더 걸려 뒤에 둔다.
PROVIDER_SCHEDULES: dict[str, Callable[..., Any]] = {
    "naver": sch_002,
    "gdelt": sch_003,
    "newsapi": sch_004,
    "google_news": sch_001,
    # SNS(COL-005)는 Provider별 스케줄 기능 ID가 명세에 없어 공용 구현을 바로
    # 부른다. 판정·실행 규칙은 뉴스 Provider와 같다.
    "youtube": partial(run_provider_collection_schedule, provider="youtube"),
    "reddit": partial(run_provider_collection_schedule, provider="reddit"),
}


# 본문 수집 단계를 결과 목록에서 가리키는 이름. Provider 이름이 아니라 "본문을
# 어떻게 읽었는가"를 나타내므로 수집 Provider와 겹치지 않는 값을 쓴다.
CONTENT_FETCH_STEP = "content-fetch"

# 관심사 주기 재계산 단계를 결과 목록에서 가리키는 이름.
INTEREST_RECALCULATION_STEP = "interest-recalculation"

# 수동 실행이 큐에 넣는 수집 Job의 유형. 수동 실행 API는 이 Job만 등록하고 바로
# 응답하며, 실제 수집은 Scheduler tick이 이 Job을 집어 처리한다.
MANUAL_COLLECTION_JOB_TYPE = "global_collection_run"

# 수동 실행 Job 처리 단계를 결과 목록에서 가리키는 이름.
MANUAL_RUN_STEP = "manual-collection-run"


def _summarize_manual_run(
    source_key: str, results: list[CollectionScheduleResult]
) -> dict[str, object]:
    """수동 실행 수집 결과를 Job에 저장할 요약으로 압축한다.

    부르는 쪽(Service)이 `GET /jobs/{job_id}`로 확인할 값이다. Provider별 저장
    건수를 합산하고, 하나라도 실패가 있으면 partial, 전부 실패면 failed로 정한다.
    """
    providers = [
        provider
        for result in results
        for provider in result.results
        if isinstance(provider, dict)
    ]
    failed = [item for item in providers if item.get("status") == "failed"]
    if not providers:
        status = "skipped"
    elif len(failed) == len(providers):
        status = "failed"
    elif failed:
        status = "partial"
    else:
        status = "completed"

    def _total(field: str) -> int:
        """Provider 결과에서 정수 건수 필드를 합산한다."""
        return sum(
            value
            for item in providers
            if isinstance(value := item.get(field), int)
            and not isinstance(value, bool)
        )

    return {
        "source_key": source_key,
        "status": status,
        "keyword_count": len(results),
        "fetched_count": _total("fetched_count"),
        "created_count": _total("created_count"),
        "duplicate_count": _total("duplicate_count"),
    }


@dataclass(frozen=True, slots=True)
class CollectionScheduler:
    """등록된 수집 스케줄을 주기적으로 판정·실행하는 Scheduler."""

    database_url: str
    credentials: CollectionCredentials
    tick_seconds: int
    # tick마다 본문을 채울 문서 수. 0이면 본문 수집 단계를 건너뛴다.
    content_fetch_limit: int = 0
    # 이 Scheduler 프로세스의 Job Lease 소유자 식별자.
    worker_id: str = "collection-scheduler"
    # tick마다 처리할 수동 실행 Job 수. 수집 하나가 관심 Topic이 많으면 오래
    # 걸리므로 기본 1개씩만 집어 다른 tick 작업이 과하게 밀리지 않게 한다.
    manual_run_claim_limit: int = 1
    # 수동 실행 Job Lease 유지 시간(초). taxonomy 수집이 수 분 걸릴 수 있어 최대
    # 값(1시간)을 쓴다 — 수집이 끝나기 전에 Lease가 풀려 중복 처리되지 않게 한다.
    manual_run_lease_seconds: int = 3600
    # tick마다 관심사를 다시 계산할 사용자 수. 0이면 재계산 단계를 건너뛴다.
    interest_recalculation_limit: int = 0
    # 관심사 Profile을 다시 계산하기까지 기다리는 시간(시간).
    interest_recalculation_stale_hours: float = 24.0

    async def run_once(
        self, *, now: datetime | None = None, force: bool = False
    ) -> list[CollectionScheduleResult]:
        """수집 스케줄을 한 번 판정·실행하고, 이어서 본문을 채운다.

        먼저 큐에 쌓인 수동 실행 Job을 처리하고(사용자가 즉시 결과를 기다리는
        요청이므로 우선), 이어서 정기 수집을 판정·실행한 뒤 본문을 채운다.

        Args:
            now: 판정 기준 시각 (미지정 시 현재 UTC)
            force: True면 Cron 실행 시각 조건을 건너뛴다 (쿼터는 지킨다)

        Returns:
            수동 실행·Provider·Source·키워드별 판정과 실행 결과 목록. 마지막에
            본문 수집 단계의 결과가 붙는다
        """
        moment = now or datetime.now(UTC)
        results: list[CollectionScheduleResult] = []
        results.extend(await self.drain_manual_collection_runs(now=moment))
        connection: AsyncConnection[DictRow] = await AsyncConnection.connect(
            self.database_url,
            row_factory=dict_row,
        )
        try:
            for provider, schedule_feature in PROVIDER_SCHEDULES.items():
                # Provider 하나의 실패가 나머지 수집을 막지 않도록 격리한다.
                try:
                    results.extend(
                        await schedule_feature(
                            connection,
                            database_url=self.database_url,
                            credentials=self.credentials,
                            now=moment,
                            force=force,
                        )
                    )
                except Exception as error:  # noqa: BLE001 - 루프 유지가 우선
                    results.append(
                        CollectionScheduleResult(
                            provider=provider,
                            source_key=None,
                            status="skipped",
                            reason=(
                                f"{SCHEDULED_PROVIDERS[provider]} 실행 실패: "
                                f"{error}"
                            ),
                        )
                    )
        finally:
            await connection.close()
        results.extend(await self.recalculate_stale_interests(now=moment))
        results.extend(await self.fetch_pending_content())
        return results

    async def recalculate_stale_interests(
        self, *, now: datetime | None = None
    ) -> list[CollectionScheduleResult]:
        """관심사 Profile이 오래된 사용자를 골라 다시 계산한다(SCH-010).

        관심사 점수는 계산 시각 기준으로 최신성을 감쇠시키므로, 이 단계가 없으면
        저장 활동이 멈춘 사용자의 점수가 마지막 Wiki Build 시점에 고정된다.
        재계산은 Build와 달리 LLM을 호출하지 않아 tick 안에서 돌려도 값싸다.

        대상 선정이 `calculated_at` 기준이라 같은 사용자를 한 주기에 두 번 잡지
        않는다. 이 단계의 실패는 수집 tick을 멈추지 않는다.

        Args:
            now: 판정 기준 시각 (미지정 시 현재 UTC)

        Returns:
            처리한 사용자가 있으면 결과 한 건, 없으면 빈 목록
        """
        if self.interest_recalculation_limit <= 0:
            return []
        connection: AsyncConnection[DictRow] = await AsyncConnection.connect(
            self.database_url,
            row_factory=dict_row,
        )
        try:
            recalculated = await sch_010(
                connection,
                stale_after_hours=self.interest_recalculation_stale_hours,
                limit=self.interest_recalculation_limit,
                now=now,
            )
        except Exception as error:  # noqa: BLE001 - 다음 tick에서 다시 시도한다
            return [
                CollectionScheduleResult(
                    provider=INTEREST_RECALCULATION_STEP,
                    source_key=None,
                    status="skipped",
                    reason=f"관심사 재계산 실패: {error}",
                )
            ]
        finally:
            await connection.close()
        if not recalculated:
            return []
        return [
            CollectionScheduleResult(
                provider=INTEREST_RECALCULATION_STEP,
                source_key=None,
                status="completed",
                results=[asdict(item) for item in recalculated],
            )
        ]

    async def drain_manual_collection_runs(
        self, *, now: datetime | None = None
    ) -> list[CollectionScheduleResult]:
        """큐에 쌓인 수동 실행 Job을 집어 정기 수집과 같은 경로로 처리한다.

        수동 실행 API(SCH-021)는 Job만 큐에 넣고 바로 응답하므로, 실제 수집은
        여기서 한다. Job을 SKIP LOCKED·Lease로 점유해 여러 Scheduler가 떠도 같은
        Job을 두 번 돌리지 않는다. Job 하나의 수집·실패가 다른 Job이나 정기 수집을
        막지 않도록 Job 단위로 격리한다.

        Args:
            now: 다음 실행 시각 계산 기준 시각 (미지정 시 현재 UTC)

        Returns:
            처리한 Job별 수집 결과 목록. 점유한 Job이 없으면 빈 목록
        """
        moment = now or datetime.now(UTC)
        claim_connection: AsyncConnection[DictRow] = await AsyncConnection.connect(
            self.database_url,
            row_factory=dict_row,
        )
        try:
            async with claim_connection.transaction():
                await set_system_job_scope(claim_connection)
                claimed = await claim_runnable_agent_jobs(
                    claim_connection,
                    job_type=MANUAL_COLLECTION_JOB_TYPE,
                    worker_id=self.worker_id,
                    limit=self.manual_run_claim_limit,
                    lease_seconds=self.manual_run_lease_seconds,
                )
        finally:
            await claim_connection.close()

        results: list[CollectionScheduleResult] = []
        for job in claimed:
            results.append(await self._process_manual_collection_run(job, now=moment))
        return results

    async def _process_manual_collection_run(
        self, job: ClaimedAgentJob, *, now: datetime
    ) -> CollectionScheduleResult:
        """점유한 수동 실행 Job 하나를 수집하고 완료·실패로 마감한다.

        수집(sch_021)과 Job 마감은 **서로 다른 연결**로 나눈다. sch_021이 넘겨받은
        연결로 스케줄을 조회하며 트랜잭션을 열어 두므로, 같은 연결로 마감하면
        완료 UPDATE가 그 트랜잭션의 SAVEPOINT 안에 갇혀 커밋되지 않는다. 마감은
        새 연결에서 독립 트랜잭션으로 처리해 확실히 커밋한다.
        """
        source_key = str(job.payload.get("source_key") or "")
        error: Exception | None = None
        run_results: list[CollectionScheduleResult] = []
        connection: AsyncConnection[DictRow] = await AsyncConnection.connect(
            self.database_url,
            row_factory=dict_row,
        )
        try:
            _view, run_results = await sch_021(
                connection,
                source_key=source_key,
                database_url=self.database_url,
                credentials=self.credentials,
                now=now,
            )
        except Exception as collect_error:  # noqa: BLE001 - Job 단위로 실패를 가둔다
            error = collect_error
        finally:
            await connection.close()

        if error is not None:
            await self._finalize_manual_run(job, error=error)
            return CollectionScheduleResult(
                provider=MANUAL_RUN_STEP,
                source_key=source_key or None,
                status="skipped",
                reason=f"수동 수집 실패: {error}",
            )
        summary = _summarize_manual_run(source_key, run_results)
        await self._finalize_manual_run(job, summary=summary)
        return CollectionScheduleResult(
            provider=MANUAL_RUN_STEP,
            source_key=source_key or None,
            status="completed",
            results=[summary],
        )

    async def _finalize_manual_run(
        self,
        job: ClaimedAgentJob,
        *,
        summary: dict[str, object] | None = None,
        error: Exception | None = None,
    ) -> None:
        """수동 실행 Job을 새 연결에서 완료 또는 실패로 마감한다.

        마감 자체가 실패해도 삼킨다 — 그 Job은 Lease가 만료되면 다음 tick에서
        회수된다. 정기 수집·다른 Job까지 막지 않기 위함이다.
        """
        connection: AsyncConnection[DictRow] = await AsyncConnection.connect(
            self.database_url,
            row_factory=dict_row,
        )
        try:
            async with connection.transaction():
                await set_system_job_scope(connection)
                if error is not None:
                    await fail_agent_job(
                        connection,
                        job=job,
                        worker_id=self.worker_id,
                        error_code="collection_run_failed",
                        error_message=str(error),
                        retryable=False,
                    )
                else:
                    await complete_agent_job(
                        connection,
                        job=job,
                        worker_id=self.worker_id,
                        result=summary or {},
                    )
        except Exception:  # noqa: BLE001 - 다음 tick의 Lease 만료로 회수된다
            logger.exception("수동 수집 Job 마감에 실패했습니다: %s", job.job_id)
        finally:
            await connection.close()

    async def fetch_pending_content(self) -> list[CollectionScheduleResult]:
        """본문이 비어 있는 수집 문서를 Batch로 점유해 본문을 채운다.

        수집 단계는 URL만 저장하고 본문은 `content_status='pending'`으로 남긴다.
        본문을 채우는 쪽이 아무도 돌지 않으면 근거로 쓸 수 없는 문서만 풀에
        쌓인다 — 실제로 로컬 DB에는 마지막 본문 수집(2026-07-29) 이후 pending
        194건이 본문 없이 남아 있었다. `global-content` Worker를 사람이 직접
        실행해야만 채워졌기 때문이다. tick마다 조금씩 비워 그 구멍을 막는다.

        여러 Scheduler·Worker가 동시에 돌아도 안전하다. 대상 점유가
        `FOR UPDATE SKIP LOCKED`(claim_global_articles_for_fetch)라 같은 문서를
        두 번 읽지 않는다.

        Returns:
            처리한 문서가 있으면 결과 한 건, 없으면 빈 목록
        """
        if self.content_fetch_limit <= 0:
            return []
        try:
            fetched = await run_global_content_fetch_batch(
                database_url=self.database_url,
                limit=self.content_fetch_limit,
            )
        except Exception as error:  # noqa: BLE001 - 다음 tick에서 다시 시도한다
            return [
                CollectionScheduleResult(
                    provider=CONTENT_FETCH_STEP,
                    source_key=None,
                    status="skipped",
                    reason=f"본문 수집 실패: {error}",
                )
            ]
        if not fetched:
            return []
        return [
            CollectionScheduleResult(
                provider=CONTENT_FETCH_STEP,
                source_key=None,
                status="completed",
                results=fetched,
            )
        ]


def build_collection_credentials(settings: Settings) -> CollectionCredentials:
    """환경 설정에서 수집 Provider 자격 증명과 Endpoint를 모은다.

    Scheduler 기동(build_scheduler)과 API의 수동 실행(SCH-021)이 같은 자격
    증명을 쓰도록 한곳에서 만든다.

    Args:
        settings: 자격 증명을 읽을 환경 설정

    Returns:
        수집 Provider에 넘길 자격 증명 묶음
    """
    return CollectionCredentials(
        naver_client_id=settings.naver_client_id,
        naver_client_secret=(
            settings.naver_client_secret.get_secret_value()
            if settings.naver_client_secret
            else None
        ),
        gdelt_base_url=settings.gdelt_base_url,
        news_api_key=(
            settings.news_api_key.get_secret_value()
            if settings.news_api_key
            else None
        ),
    )


def build_scheduler(settings: Settings | None = None) -> CollectionScheduler:
    """설정된 수집 주기를 Scheduler 인스턴스에 등록한다.

    수집 주기·키워드는 코드가 아니라 `agent.global_sources` row가 소유하므로,
    여기서는 DB 연결과 Provider 자격 증명만 묶는다.

    Args:
        settings: 사용할 환경 설정 (미지정 시 환경변수에서 읽는다)

    Returns:
        수집 스케줄을 판정·실행할 수 있는 Scheduler

    Raises:
        RuntimeError: AGENT_DATABASE_URL이 없을 때
    """
    resolved = settings or load_settings()
    if not resolved.agent_database_url:
        raise RuntimeError("AGENT_DATABASE_URL이 필요합니다.")
    return CollectionScheduler(
        database_url=resolved.agent_database_url,
        credentials=build_collection_credentials(resolved),
        tick_seconds=resolved.collection_scheduler_tick_seconds,
        content_fetch_limit=resolved.collection_content_fetch_limit,
        interest_recalculation_limit=resolved.interest_recalculation_limit,
        interest_recalculation_stale_hours=(
            resolved.interest_recalculation_stale_hours
        ),
    )


async def run_collection_scheduler_loop(
    scheduler: CollectionScheduler,
    *,
    tick_seconds: int | None = None,
    max_ticks: int | None = None,
    on_tick: Callable[[list[CollectionScheduleResult]], None] | None = None,
) -> None:
    """수집 스케줄을 tick 간격으로 반복 판정·실행한다.

    tick마다 `run_once`를 await하므로 이전 판정·수집이 끝나기 전에 다음 tick이
    시작되지 않는다. 즉 같은 프로세스 안에서 수집이 겹치지 않는다. 한 tick에서
    난 예외는 기록만 하고 루프를 유지한다 — 일시적인 DB 장애로 Scheduler가
    영영 죽으면 안 되기 때문이다.

    Args:
        scheduler: 실행할 Scheduler
        tick_seconds: 확인 간격(초). 미지정 시 Scheduler 설정값을 쓴다
        max_ticks: 최대 반복 횟수 (테스트용, None이면 무한)
        on_tick: tick 결과를 받을 Callback
    """
    # 0은 "대기 없음"이므로 falsy 판정(or)으로 기본값에 떨어지면 안 된다.
    interval = scheduler.tick_seconds if tick_seconds is None else tick_seconds
    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        try:
            results = await scheduler.run_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 다음 tick에서 다시 시도한다
            logger.exception("수집 Scheduler tick이 실패했습니다.")
        else:
            if on_tick is not None:
                on_tick(results)
        ticks += 1
        if max_ticks is not None and ticks >= max_ticks:
            return
        await asyncio.sleep(interval)
