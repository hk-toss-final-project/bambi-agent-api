"""Agent API 서버 실행 진입점.

Windows의 psycopg 비동기 연결은 기본 ProactorEventLoop를 지원하지 않아,
`uv run uvicorn app.main:app`으로 띄우면 DB Pool이 붙지 못하고 모든 요청이
SERVICE_NOT_READY로 실패한다. 이 진입점은 다른 스크립트와 같은 방식으로
Selector 루프를 만들고 그 위에서 uvicorn Server를 실행한다.

실행: uv run python scripts/run_api.py [--host <host>] [--port <n>] [--reload]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8010
APP_PATH = "app.main:app"


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """서버 Host·Port와 자동 재시작 여부를 읽는다."""
    parser = argparse.ArgumentParser(description="Agent API 서버를 실행한다.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="바인딩할 Host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="바인딩할 Port")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="코드 변경 시 자동 재시작 (uvicorn 기본 실행 경로를 사용한다)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Selector 루프에서 uvicorn Server를 실행한다.

    `--reload`는 uvicorn이 자식 프로세스를 직접 띄우는 방식이라 이 진입점의
    루프 설정이 전달되지 않는다. 그래서 재시작 모드는 uvicorn 기본 실행에
    맡기고, Windows에서는 DB가 필요한 요청이 실패할 수 있음을 알린다.
    """
    arguments = parse_arguments(argv)
    if arguments.reload:
        if sys.platform == "win32":
            print(
                "경고: --reload는 Windows에서 Selector 루프를 적용하지 못해 "
                "DB 연결이 실패할 수 있습니다.",
                file=sys.stderr,
            )
        uvicorn.run(APP_PATH, host=arguments.host, port=arguments.port, reload=True)
        return 0

    config = uvicorn.Config(APP_PATH, host=arguments.host, port=arguments.port)
    server = uvicorn.Server(config)
    # psycopg async 모드는 Windows 기본 ProactorEventLoop를 지원하지 않는다.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(server.serve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
