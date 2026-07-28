"""수집 Scheduler 런타임.

등록된 Global Source의 수집 주기를 판정하고 실행하는 Scheduler 본체와 상주
루프를 제공한다. CLI 진입점(`scheduler/main.py`)과 API 서버 기동
(`app/main.py`)이 같은 런타임을 공유하도록 진입점에서 분리했다.

시계는 프로세스 하나만 돌려야 같은 수집이 중복 실행되지 않는다. API 서버를
여러 인스턴스로 띄우는 배포에서는 서버 내장 Scheduler를
`ENABLE_COLLECTION_SCHEDULER=false`로 끄고 CLI Scheduler를 한 벌만 띄운다.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.config import Settings, load_settings
from .collection import (
    SCHEDULED_PROVIDERS,
    CollectionCredentials,
    CollectionScheduleResult,
    sch_002,
    sch_003,
    sch_004,
)

type DictRow = dict[str, Any]

logger = logging.getLogger(__name__)

# Provider 이름과 정기 수집 스케줄 기능의 연결.
PROVIDER_SCHEDULES: dict[str, Callable[..., Any]] = {
    "naver": sch_002,
    "gdelt": sch_003,
    "newsapi": sch_004,
}


@dataclass(frozen=True, slots=True)
class CollectionScheduler:
    """등록된 수집 스케줄을 주기적으로 판정·실행하는 Scheduler."""

    database_url: str
    credentials: CollectionCredentials
    tick_seconds: int

    async def run_once(
        self, *, now: datetime | None = None, force: bool = False
    ) -> list[CollectionScheduleResult]:
        """등록된 모든 Provider의 수집 스케줄을 한 번 판정하고 실행한다.

        Args:
            now: 판정 기준 시각 (미지정 시 현재 UTC)
            force: True면 Cron 실행 시각 조건을 건너뛴다 (쿼터는 지킨다)

        Returns:
            Provider·Source·키워드별 판정과 실행 결과 목록
        """
        moment = now or datetime.now(UTC)
        connection: AsyncConnection[DictRow] = await AsyncConnection.connect(
            self.database_url,
            row_factory=dict_row,
        )
        try:
            results: list[CollectionScheduleResult] = []
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
            return results
        finally:
            await connection.close()


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
        credentials=CollectionCredentials(
            naver_client_id=resolved.naver_client_id,
            naver_client_secret=(
                resolved.naver_client_secret.get_secret_value()
                if resolved.naver_client_secret
                else None
            ),
            gdelt_base_url=resolved.gdelt_base_url,
            news_api_key=(
                resolved.news_api_key.get_secret_value()
                if resolved.news_api_key
                else None
            ),
        ),
        tick_seconds=resolved.collection_scheduler_tick_seconds,
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
