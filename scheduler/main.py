"""정기 작업을 등록하고 Scheduler 프로세스를 실행하는 진입점.

API 서버·Worker와 독립된 프로세스로 실행한다. 일정 간격(tick)마다 등록된
Global Source의 수집 주기를 확인해, 실행할 차례가 된 Provider만 수집
기능(SCH-002·SCH-003·SCH-004)으로 넘긴다.

Scheduler 본체는 `scheduler/runtime.py`에 있다. API 서버도 기동 시 같은
런타임을 백그라운드로 띄우므로(`ENABLE_COLLECTION_SCHEDULER`), 이 CLI는 서버
내장 Scheduler를 끈 배포나 수동 점검용이다. **시계는 한 벌만 돌려야 한다.**

실행:
    uv run python -m scheduler.main            # 상주 모드
    uv run python -m scheduler.main --once     # 한 번만 판정·실행
"""

from __future__ import annotations

import argparse
import asyncio
import json
import selectors
import socket
import sys
from dataclasses import asdict

from scheduler.api import (
    CollectionScheduleResult,
    build_scheduler,
    run_collection_scheduler_loop,
)


def _parse_args() -> argparse.Namespace:
    """Scheduler 명령행 옵션을 파싱한다."""
    parser = argparse.ArgumentParser(description="Report Builder Agent Scheduler")
    parser.add_argument(
        "--once",
        action="store_true",
        help="상주하지 않고 스케줄을 한 번만 판정·실행한다",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Cron 실행 시각 조건을 건너뛴다 (일일 호출 한도는 그대로 지킨다)",
    )
    parser.add_argument(
        "--tick-seconds",
        type=int,
        help="상주 모드에서 수집 주기 도달 여부를 다시 확인하는 간격(초)",
    )
    return parser.parse_args()


def _print_results(results: list[CollectionScheduleResult]) -> None:
    """판정·실행 결과를 JSON Line으로 출력한다."""
    if not results:
        return
    print(
        json.dumps(
            [asdict(result) for result in results],
            ensure_ascii=False,
            default=str,
        ),
        flush=True,
    )


async def _run() -> None:
    """단발 또는 상주 모드로 수집 Scheduler를 실행한다."""
    args = _parse_args()
    if args.force and not args.once:
        # 상주 모드에서 force를 쓰면 tick마다 수집해 호출 한도를 태운다.
        raise RuntimeError("--force는 --once와 함께만 사용할 수 있습니다.")
    scheduler = build_scheduler()
    tick_seconds = args.tick_seconds or scheduler.tick_seconds
    if args.once:
        _print_results(await scheduler.run_once(force=args.force))
        return
    print(
        f"수집 Scheduler를 시작합니다 (host={socket.gethostname()}, "
        f"tick={tick_seconds}s)",
        file=sys.stderr,
        flush=True,
    )
    await run_collection_scheduler_loop(
        scheduler,
        tick_seconds=tick_seconds,
        on_tick=_print_results,
    )


def main() -> None:
    """Scheduler 프로세스를 시작하고 종료 신호를 처리한다."""
    # psycopg async 모드는 Windows 기본 ProactorEventLoop를 지원하지 않는다.
    loop_factory = (
        (lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
        if sys.platform == "win32"
        else None
    )
    try:
        asyncio.run(_run(), loop_factory=loop_factory)
    except KeyboardInterrupt:
        print("Scheduler를 종료합니다.", file=sys.stderr)


if __name__ == "__main__":
    main()
