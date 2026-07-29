"""Worker CLI 진입점의 출력 설정을 검증한다.

Windows 콘솔(cp949)에서 이모지가 섞인 결과를 출력하다 프로세스가 죽지 않도록,
표준 출력 인코딩을 UTF-8로 맞추는 동작만 확인한다. Worker 실행 자체는 각
기능 테스트가 담당한다.
"""

import sys
from typing import Any

import pytest

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
