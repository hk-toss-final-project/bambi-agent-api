"""애플리케이션 로깅 설정(app/logging_config.py) 검증.

핸들러 구성이 중복 없이 이뤄지는지, request_id가 레코드에 실리는지,
파일 로그가 JSON 한 줄 형식으로 쓰이는지를 실제 root 로거 오염 없이
확인한다.
"""

from __future__ import annotations

import json
import logging

import pytest

from app.logging_config import (
    JsonLogFormatter,
    RequestContextFilter,
    configure_logging,
    request_id_var,
    trace_id_var,
)


@pytest.fixture
def clean_root_logger():
    """테스트 동안 root 로거 상태를 격리하고 끝나면 복원한다."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    saved_flag = getattr(root, "_bambi_logging_configured", False)
    root.handlers = []
    if hasattr(root, "_bambi_logging_configured"):
        delattr(root, "_bambi_logging_configured")
    yield root
    root.handlers = saved_handlers
    root.setLevel(saved_level)
    if saved_flag:
        root._bambi_logging_configured = True
    elif hasattr(root, "_bambi_logging_configured"):
        delattr(root, "_bambi_logging_configured")


def _own_handlers(root: logging.Logger) -> list[logging.Handler]:
    """pytest 로깅 플러그인이 얹는 캡처 핸들러를 제외한 우리 핸들러만 반환한다."""
    return [
        handler
        for handler in root.handlers
        if handler.__class__.__module__ != "_pytest.logging"
    ]


def test_configure_logging_is_idempotent(clean_root_logger, tmp_path) -> None:
    """반복 호출해도 핸들러가 중복으로 쌓이지 않는다(테스트의 create_app 반복 대비)."""
    configure_logging(log_level="INFO", log_directory=str(tmp_path / "logs"))
    first_count = len(_own_handlers(clean_root_logger))

    configure_logging(log_level="INFO", log_directory=str(tmp_path / "logs"))

    assert len(_own_handlers(clean_root_logger)) == first_count == 2  # 콘솔 + 파일


def test_configure_logging_without_directory_skips_file_handler(
    clean_root_logger,
) -> None:
    """LOG_DIR이 빈 값이면 콘솔 핸들러만 구성한다(다중 Worker 배포용)."""
    configure_logging(log_level="INFO", log_directory="")

    handlers = _own_handlers(clean_root_logger)
    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.StreamHandler)


def test_file_log_is_json_with_request_id(clean_root_logger, tmp_path) -> None:
    """파일 로그는 request_id를 포함한 한 줄 JSON으로 쓰인다."""
    log_dir = tmp_path / "logs"
    configure_logging(log_level="INFO", log_directory=str(log_dir))

    request_token = request_id_var.set("req-123")
    trace_token = trace_id_var.set("trace-456")
    try:
        logging.getLogger("agent.test").info("이력 저장소: %s", "PostgreSQL")
    finally:
        trace_id_var.reset(trace_token)
        request_id_var.reset(request_token)
    for handler in clean_root_logger.handlers:
        handler.flush()

    line = (log_dir / "agent-api.log").read_text(encoding="utf-8").strip()
    payload = json.loads(line)
    assert payload["message"] == "이력 저장소: PostgreSQL"
    assert payload["request_id"] == "req-123"
    assert payload["trace_id"] == "trace-456"
    assert payload["logger"] == "agent.test"
    assert payload["level"] == "INFO"


def test_request_context_filter_defaults_to_dash() -> None:
    """요청 컨텍스트 밖(스케줄러 등)에서는 request_id가 '-'로 남는다."""
    record = logging.LogRecord("x", logging.INFO, "f", 1, "msg", None, None)

    assert RequestContextFilter().filter(record) is True
    assert record.request_id == "-"
    assert record.trace_id == "-"


def test_request_context_filter_keeps_explicit_request_id() -> None:
    """extra로 이미 실린 request_id는 덮어쓰지 않는다(컨텍스트 밖 예외 핸들러용)."""
    record = logging.LogRecord("x", logging.ERROR, "f", 1, "msg", None, None)
    record.request_id = "explicit-id"

    assert RequestContextFilter().filter(record) is True
    assert record.request_id == "explicit-id"


def test_json_formatter_serializes_exception() -> None:
    """예외 정보가 있으면 JSON에 exception 필드로 직렬화한다."""
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord(
            "x", logging.ERROR, "f", 1, "실패", None, sys.exc_info()
        )
    text = JsonLogFormatter().format(record)
    payload = json.loads(text)
    assert payload["level"] == "ERROR"
    assert "ValueError: boom" in payload["exception"]
