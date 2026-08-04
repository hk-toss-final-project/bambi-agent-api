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
