"""Agent API 공통 예외 타입과 처리기 등록 계약."""

from dataclasses import dataclass

from fastapi import FastAPI


@dataclass(frozen=True, slots=True)
class ErrorDetail:
    """클라이언트에 노출 가능한 공통 오류 정보."""

    code: str
    message: str
    retryable: bool = False


class AgentApiError(RuntimeError):
    """Agent API의 예상 가능한 도메인 오류."""


def register_exception_handlers(application: FastAPI) -> None:
    """[SYS-007] 공통 오류 응답을 만드는 전역 예외 처리기를 등록한다."""
    raise NotImplementedError("[SYS-007] 공통 예외 처리 구현이 필요합니다.")
