"""개발 환경에서 Bambi Agent API 서버를 실행하는 명령 진입점."""

import uvicorn


def main() -> None:
    """Uvicorn으로 FastAPI 애플리케이션을 실행한다."""
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
