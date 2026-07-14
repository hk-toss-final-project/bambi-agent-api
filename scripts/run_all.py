"""API 서버와 키워드 비서 웹 UI를 각각 별도 포트로 함께 실행하는 개발용 런처.

- Agent API      : http://127.0.0.1:8000  (app.main:app)
- 키워드 비서 UI : http://127.0.0.1:8100  (app.assistant.main:app)

실행:
    uv run python scripts/run_all.py
    uv run python scripts/run_all.py --api-port 9000 --web-port 9100

두 서버를 각각의 uvicorn 프로세스로 띄우고, 하나가 종료되거나 Ctrl+C가 들어오면
둘 다 정리한다.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time


def _spawn(app_path: str, port: int) -> subprocess.Popen[bytes]:
    """지정한 ASGI 앱을 해당 포트의 uvicorn 프로세스로 띄운다."""
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", app_path, "--port", str(port)]
    )


def main() -> None:
    """API 서버와 비서 웹 UI를 함께 실행하고 종료를 관리한다."""
    parser = argparse.ArgumentParser(description="API + 키워드 비서 UI 동시 실행")
    parser.add_argument("--api-port", type=int, default=8000, help="Agent API 포트")
    parser.add_argument("--web-port", type=int, default=8100, help="키워드 비서 UI 포트")
    args = parser.parse_args()

    processes = {
        "api": _spawn("app.main:app", args.api_port),
        "web": _spawn("app.assistant.main:app", args.web_port),
    }
    print(f"Agent API      : http://127.0.0.1:{args.api_port}")
    print(f"키워드 비서 UI : http://127.0.0.1:{args.web_port}")

    try:
        # 하나라도 먼저 종료되면 나머지도 정리한다.
        while all(process.poll() is None for process in processes.values()):
            time.sleep(1)
        for name, process in processes.items():
            if process.poll() is not None:
                print(f"[{name}] 프로세스가 종료되었습니다. 나머지도 정리합니다.")
    except KeyboardInterrupt:
        print("\n종료 신호를 받았습니다. 서버를 정리합니다.")
    finally:
        for process in processes.values():
            if process.poll() is None:
                process.terminate()


if __name__ == "__main__":
    main()
