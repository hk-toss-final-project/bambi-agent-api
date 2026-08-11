"""공유 LLM Chat Completion 경계의 재시도·사용량 반환을 검증한다."""

import pytest

from agent.llm.features import client as llm_client


class _TransientError(RuntimeError):
    """테스트용 일시적 Provider 오류."""


class _FakeResponse:
    """content와 usage_metadata를 흉내 내는 응답 Test Double."""

    def __init__(
        self,
        content: str,
        usage: dict[str, int] | None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.content = content
        self.usage_metadata = usage
        self.response_metadata = {"headers": headers or {}}


class _FakeClient:
    """호출 횟수를 기록하고 지정 순서대로 실패·성공하는 Client 대역."""

    def __init__(self, failures: int, response: _FakeResponse) -> None:
        self._failures = failures
        self._response = response
        self.calls = 0

    def invoke(self, messages: list[tuple[str, str]]) -> _FakeResponse:
        """failures 횟수만큼 일시 오류를 던진 뒤 고정 응답을 반환한다."""
        self.calls += 1
        if self.calls <= self._failures:
            raise _TransientError("일시적 오류")
        return self._response


def _patch_boundary(
    monkeypatch: pytest.MonkeyPatch, fake: _FakeClient
) -> None:
    """실제 SDK 접근 없이 클라이언트·오류 타입·Backoff를 대체한다."""
    monkeypatch.setattr(llm_client, "_get_client", lambda *args: fake)
    monkeypatch.setattr(
        llm_client, "_transient_error_types", lambda: (_TransientError,)
    )
    monkeypatch.setattr(llm_client, "_BACKOFF_BASE_SECONDS", 0)


def test_complete_with_usage_retries_transient_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """일시적 오류는 Backoff 후 재시도해 성공 응답과 사용량을 반환한다."""
    fake = _FakeClient(
        failures=1,
        response=_FakeResponse(
            " 결과 ", {"input_tokens": 12, "output_tokens": 34}
        ),
    )
    _patch_boundary(monkeypatch, fake)

    completion = llm_client.complete_with_usage("system", "user", model="test-model")

    assert fake.calls == 2
    assert completion.text == "결과"
    assert completion.model == "test-model"
    assert completion.input_tokens == 12
    assert completion.output_tokens == 34


def test_complete_with_usage_raises_after_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """최대 시도 횟수를 넘긴 일시적 오류는 그대로 전파한다."""
    fake = _FakeClient(failures=5, response=_FakeResponse("unused", None))
    _patch_boundary(monkeypatch, fake)

    with pytest.raises(_TransientError):
        llm_client.complete_with_usage("system", "user", max_attempts=2)

    assert fake.calls == 2


def test_complete_with_usage_skips_call_for_blank_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """공백뿐인 user 프롬프트는 호출 없이 빈 결과를 반환한다."""
    fake = _FakeClient(failures=0, response=_FakeResponse("unused", None))
    _patch_boundary(monkeypatch, fake)

    completion = llm_client.complete_with_usage("system", "   ")

    assert fake.calls == 0
    assert completion.text == ""
    assert completion.input_tokens == 0


def test_complete_returns_text_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """호환 진입점 complete는 같은 경로로 호출해 텍스트만 반환한다."""
    fake = _FakeClient(failures=0, response=_FakeResponse("본문", None))
    _patch_boundary(monkeypatch, fake)

    assert llm_client.complete("system", "user", model="test-model") == "본문"
    assert fake.calls == 1


def test_complete_with_usage_returns_request_and_rate_limit_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """성공 응답의 요청 ID와 Rate Limit 헤더를 호출 결과에 보존한다."""
    fake = _FakeClient(
        failures=0,
        response=_FakeResponse(
            "본문",
            {"input_tokens": 1, "output_tokens": 2},
            {
                "X-Request-ID": "req-test",
                "X-RateLimit-Remaining-Requests": "9",
                "Content-Type": "application/json",
            },
        ),
    )
    _patch_boundary(monkeypatch, fake)

    completion = llm_client.complete_with_usage("system", "user")

    assert completion.request_id == "req-test"
    assert completion.rate_limit_headers == {
        "x-ratelimit-remaining-requests": "9"
    }


def test_capture_llm_calls_collects_usage_and_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Worker Capture Context가 호출 사용량과 Provider 헤더를 함께 수집한다."""
    fake = _FakeClient(
        failures=0,
        response=_FakeResponse(
            "본문",
            {"input_tokens": 11, "output_tokens": 7},
            {
                "X-Request-ID": "req-capture",
                "X-RateLimit-Remaining-Tokens": "999",
            },
        ),
    )
    _patch_boundary(monkeypatch, fake)

    with llm_client.capture_llm_calls() as captured:
        llm_client.complete_with_usage("system", "user", model="test-model")

    assert len(captured) == 1
    assert captured[0].model == "test-model"
    assert captured[0].input_tokens == 11
    assert captured[0].output_tokens == 7
    assert captured[0].request_id == "req-capture"
    assert captured[0].headers["x-ratelimit-remaining-tokens"] == "999"


class _QuotaError(RuntimeError):
    """재시도하면 안 되는 사용량 한도 오류."""

    code = "insufficient_quota"


class _QuotaClient:
    """호출할 때마다 quota 오류를 발생시키는 Client 대역."""

    def __init__(self) -> None:
        """호출 횟수를 0으로 초기화한다."""
        self.calls = 0

    def invoke(self, messages: list[tuple[str, str]]) -> _FakeResponse:
        """quota 오류를 발생시킨다."""
        self.calls += 1
        raise _QuotaError("결제 한도 초과")


def test_complete_does_not_retry_quota_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """사용자 조치가 필요한 quota 오류는 첫 실패에서 바로 전파한다."""
    fake = _QuotaClient()
    monkeypatch.setattr(llm_client, "_get_client", lambda *args: fake)
    monkeypatch.setattr(llm_client, "_transient_error_types", lambda: (_QuotaError,))

    with pytest.raises(_QuotaError):
        llm_client.complete_with_usage("system", "user", max_attempts=3)

    assert fake.calls == 1
