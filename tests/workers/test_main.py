"""Worker CLI 진입점의 출력 설정을 검증한다.

Windows 콘솔(cp949)에서 이모지가 섞인 결과를 출력하다 프로세스가 죽지 않도록,
표준 출력 인코딩을 UTF-8로 맞추는 동작만 확인한다. Worker 실행 자체는 각
기능 테스트가 담당한다.
"""

import asyncio
import sys
from argparse import Namespace
from typing import Any

import pytest

from app.config import Settings
from workers import main as worker_main
from workers.main import configure_output_encoding


class _RecordingStream:
    """reconfigure 호출 인자를 기록하는 표준 출력 대역."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def reconfigure(self, **kwargs: Any) -> None:
        """인코딩 재설정 인자를 기록한다."""
        self.calls.append(kwargs)


class _UnsupportedStream:
    """reconfigure를 지원하지 않는 스트림 대역 (리다이렉트된 출력 등)."""


class _FailingStream:
    """reconfigure가 실패하는 스트림 대역."""

    def reconfigure(self, **kwargs: Any) -> None:
        """인코딩을 바꿀 수 없는 스트림을 흉내 낸다."""
        raise OSError("인코딩을 바꿀 수 없습니다.")


def test_configure_output_encoding_sets_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """표준 출력·오류를 UTF-8로 맞추는지 검증한다."""
    stdout, stderr = _RecordingStream(), _RecordingStream()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    configure_output_encoding()

    assert stdout.calls == [{"encoding": "utf-8", "errors": "backslashreplace"}]
    assert stderr.calls == [{"encoding": "utf-8", "errors": "backslashreplace"}]


def test_configure_output_encoding_tolerates_unsupported_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """인코딩을 바꿀 수 없는 스트림에서도 예외 없이 넘어가는지 검증한다."""
    monkeypatch.setattr(sys, "stdout", _UnsupportedStream())
    monkeypatch.setattr(sys, "stderr", _FailingStream())

    configure_output_encoding()


def test_run_batch_once_dispatches_url_collection_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI의 url-collection 선택이 URL Job Batch 실행기로 연결되는지 검증한다."""
    recorded: dict[str, Any] = {}

    async def fake_url_batch(**kwargs: Any) -> list[dict[str, object]]:
        """URL Batch 실행 인자를 기록한다."""
        recorded.update(kwargs)
        return [{"job_id": "url-job-1", "status": "completed"}]

    monkeypatch.setattr(worker_main, "run_url_collection_batch", fake_url_batch)
    args = Namespace(
        worker="url-collection",
        limit=7,
        lease_seconds=180,
    )
    settings = Settings(
        agent_database_url="postgresql://test",
        personal_wiki_worker_batch_size=1,
        personal_wiki_job_lease_seconds=600,
    )

    result = asyncio.run(
        worker_main._run_batch_once(args, settings, worker_id="url-worker-1")
    )

    assert result[0]["status"] == "completed"
    assert recorded == {
        "database_url": "postgresql://test",
        "worker_id": "url-worker-1",
        "limit": 7,
        "lease_seconds": 180,
    }


def test_run_batch_once_dispatches_openai_batch_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI의 openai-batch 선택이 Secret과 제출·Poll 설정을 전용 Worker에 전달한다."""
    recorded: dict[str, Any] = {}

    async def fake_batch_cycle(**kwargs: Any) -> list[dict[str, object]]:
        """Batch Cycle 인자를 기록하고 고정 결과를 반환한다."""
        recorded.update(kwargs)
        return [{"batch_id": "batch-1", "status": "submitted"}]

    monkeypatch.setattr(worker_main, "run_openai_batch_cycle", fake_batch_cycle)
    settings = Settings(
        agent_database_url="postgresql://test",
        openai_api_key="test-openai-secret",
        openai_batch_max_items=400,
        openai_batch_max_submissions=2,
        openai_batch_poll_limit=20,
        openai_batch_poll_interval_seconds=45,
        openai_batch_poll_lease_seconds=90,
    )

    result = asyncio.run(
        worker_main._run_batch_once(
            Namespace(worker="openai-batch"),
            settings,
            worker_id="batch-worker-1",
        )
    )

    assert result[0]["status"] == "submitted"
    assert recorded["api_key"] == "test-openai-secret"
    assert recorded["max_items"] == 400
    assert recorded["poll_interval_seconds"] == 45


def test_run_batch_once_uses_dedicated_report_batch_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report Worker가 Personal Wiki와 분리된 Batch 상한을 사용한다."""
    recorded: dict[str, Any] = {}

    async def fake_report_worker(**kwargs: Any) -> list[dict[str, object]]:
        """Report Worker 실행 인자를 기록한다."""
        recorded.update(kwargs)
        return []

    monkeypatch.setattr(worker_main, "worker_003", fake_report_worker)
    args = Namespace(
        worker="report-generation",
        model=None,
        limit=None,
        concurrency=None,
        lease_seconds=None,
    )
    settings = Settings(
        agent_database_url="postgresql://test",
        personal_wiki_worker_batch_size=20,
        report_worker_batch_size=6,
        report_job_concurrency=2,
    )

    asyncio.run(worker_main._run_batch_once(args, settings, "report-worker-1"))

    assert recorded["limit"] == 6
    assert recorded["concurrency"] == 2


def test_run_batch_once_dispatches_briefing_preparation_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI 브리핑 준비 유형이 전용 Worker와 Rate 예약 설정으로 연결된다."""
    recorded: dict[str, Any] = {}

    async def fake_briefing_worker(**kwargs: Any) -> list[dict[str, object]]:
        """브리핑 준비 Worker 실행 인자를 기록한다."""
        recorded.update(kwargs)
        return []

    monkeypatch.setattr(
        worker_main,
        "run_briefing_preparation_batch",
        fake_briefing_worker,
    )
    args = Namespace(
        worker="briefing-preparation",
        model=None,
        limit=None,
        concurrency=None,
        lease_seconds=None,
    )
    settings = Settings(
        agent_database_url="postgresql://test",
        report_worker_batch_size=8,
        report_job_concurrency=2,
        briefing_openai_requests_per_job=7,
        briefing_openai_tokens_per_job=28_000,
    )

    asyncio.run(worker_main._run_batch_once(args, settings, "briefing-worker-1"))

    assert recorded["limit"] == 8
    assert recorded["concurrency"] == 2
    assert recorded["rate_limit_policy"].estimated_requests == 7
    assert recorded["rate_limit_policy"].estimated_tokens == 28_000


def test_run_loop_dispatches_resident_url_collection_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI 상주 모드가 personal_wiki_url Queue 소비 루프를 계속 실행하도록 연결되는지 검증한다."""
    recorded: dict[str, Any] = {}
    args = Namespace(
        worker="url-collection",
        worker_id="url-worker-1",
        limit=4,
        lease_seconds=120,
        loop=True,
        interval_seconds=5,
    )
    settings = Settings(agent_database_url="postgresql://test")

    async def fake_consume(**kwargs: Any) -> list[dict[str, object]]:
        """상주 Queue 소비 인자를 기록하고 즉시 종료한다."""
        recorded.update(kwargs)
        return []

    monkeypatch.setattr(worker_main, "_parse_args", lambda: args)
    monkeypatch.setattr(worker_main, "load_settings", lambda: settings)
    monkeypatch.setattr(worker_main, "wc_001", fake_consume)

    asyncio.run(worker_main._run())

    assert recorded["job_type"] == "personal_wiki_url"
    assert recorded["interval_seconds"] == 5
    assert recorded["max_batches"] is None
    assert recorded["worker_id"] == "url-worker-1"


def test_worker_entrypoint_configures_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    """Worker 진입점이 로깅을 구성한다.

    Worker는 FastAPI 앱을 만들지 않으므로 여기서 부르지 않으면 root에 핸들러가
    없어 agent.*·workers.* 로거 출력이 통째로 버려진다. 2026-08-05 배포 Worker
    stdout에 logger 라인이 0건이었고, 진단이 필요한 순간에 로그가 없었다.
    """
    configured: list[dict[str, str]] = []

    def fake_configure(*, log_level: str, log_directory: str) -> None:
        """로깅 구성 호출을 기록한다."""
        configured.append({"log_level": log_level, "log_directory": log_directory})

    monkeypatch.setattr(worker_main, "configure_logging", fake_configure)
    monkeypatch.setattr(
        worker_main, "_parse_args", lambda: Namespace(worker="personal-wiki")
    )

    class _Settings:
        """진입점이 읽는 최소 설정."""

        log_level = "INFO"
        log_directory = "logs"
        agent_database_url = ""

    monkeypatch.setattr(worker_main, "load_settings", lambda: _Settings())

    with pytest.raises(RuntimeError):
        # DB URL이 비어 있어 곧바로 중단되지만, 로깅 구성은 그 전에 끝나야 한다.
        asyncio.run(worker_main._run())

    assert configured == [{"log_level": "INFO", "log_directory": "logs"}]
