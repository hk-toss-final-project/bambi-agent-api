"""애플리케이션 로깅 설정과 요청 추적 컨텍스트 연동.

그동안 앱 로거(agent.*, app.*)는 root 핸들러가 없어 콘솔에조차 출력되지
않았다 — 비서 이력 저장소 폴백 같은 침묵 실패를 알 수 없었다. 이 모듈은
콘솔(사람이 읽는 형식)과 회전 파일(JSON, 수집기 연동용) 두 핸들러를
구성하고, RequestTracingMiddleware가 심는 request_id·trace_id를 모든 LogRecord에
싣는다.

파일 로그는 로컬 조회 편의용이다. 운영 수집(Cloud Logging, Loki 등)은
stdout을 소스로 쓰므로 다중 Worker 배포에서는 LOG_DIR을 비워 파일
핸들러를 끄고 콘솔만 남긴다.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from contextvars import ContextVar
from pathlib import Path

# 요청 처리 중에만 값이 있는 요청 추적 ID. 미들웨어가 설정·해제한다.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)

# 파일 핸들러 보존 일수. 자정마다 회전한다.
_LOG_BACKUP_DAYS = 14

# configure_logging이 중복 실행돼도 핸들러가 쌓이지 않게 하는 표식.
_CONFIGURED_FLAG = "_bambi_logging_configured"


class RequestContextFilter(logging.Filter):
    """현재 요청의 request_id·trace_id를 LogRecord에 싣는다."""

    def filter(self, record: logging.LogRecord) -> bool:
        """레코드에 request_id 속성을 추가하고 항상 통과시킨다.

        호출부가 extra={"request_id": ...}로 이미 실은 값은 덮어쓰지 않는다
        (컨텍스트 밖에서 실행되는 예외 핸들러 등).
        """
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get() or "-"
        if not hasattr(record, "trace_id"):
            record.trace_id = trace_id_var.get() or "-"
        return True


class JsonLogFormatter(logging.Formatter):
    """수집기(Loki, Cloud Logging 등)가 파싱하기 쉬운 한 줄 JSON 포맷."""

    def format(self, record: logging.LogRecord) -> str:
        """LogRecord를 JSON 문자열로 직렬화한다."""
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "trace_id": getattr(record, "trace_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(*, log_level: str = "INFO", log_directory: str = "logs") -> None:
    """root 로거에 콘솔·파일 핸들러를 구성한다(중복 호출 안전).

    uvicorn 로거(uvicorn.access 등)는 자체 핸들러를 유지하고 propagate하지
    않으므로 건드리지 않는다 — 여기서는 앱 로거가 전파되는 root만 구성한다.

    Args:
        log_level: root 로거 레벨 이름 (기본 INFO)
        log_directory: 회전 파일 로그 디렉터리. 빈 값이면 파일 핸들러를 끈다.
    """
    root = logging.getLogger()
    if getattr(root, _CONFIGURED_FLAG, False):
        return

    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    context_filter = RequestContextFilter()

    console = logging.StreamHandler()
    console.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s "
            "[%(request_id)s %(trace_id)s] %(message)s"
        )
    )
    console.addFilter(context_filter)
    root.addHandler(console)

    if log_directory:
        directory = Path(log_directory)
        directory.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.TimedRotatingFileHandler(
            directory / "agent-api.log",
            when="midnight",
            backupCount=_LOG_BACKUP_DAYS,
            encoding="utf-8",
        )
        file_handler.setFormatter(JsonLogFormatter())
        file_handler.addFilter(context_filter)
        root.addHandler(file_handler)

    setattr(root, _CONFIGURED_FLAG, True)
